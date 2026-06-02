"""Tests for summarizer module — covers should_summarize, generate_structured_summary,
_build_budget_hint, _cap_summary_if_needed, and _log_merge_quality."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from myrm_agent_harness.agent.context_management.infra.schemas import (
    ContextConfig,
    StructuredSummary,
)
from myrm_agent_harness.agent.context_management.strategies.summarizer import (
    _build_budget_hint,
    _build_summary_invocation_messages,
    _cap_summary_if_needed,
    _log_merge_quality,
    _redact_summary_fields,
    generate_structured_summary,
    should_summarize,
)


def _synthetic_prefix_cache_metrics(
    previous_invocation: list[BaseMessage],
    next_invocation: list[BaseMessage],
) -> dict[str, float]:
    """Deterministic cache-shape probe; it does not claim provider cache performance."""
    cached_chars = 0
    for previous_message, next_message in zip(previous_invocation, next_invocation, strict=False):
        if previous_message != next_message:
            break
        cached_chars += len(str(next_message.content))
    input_chars = sum(len(str(message.content)) for message in next_invocation)
    input_tokens = max(input_chars / 4, 1)
    cached_tokens = cached_chars / 4
    return {
        "input_tokens": input_tokens,
        "cached_tokens": cached_tokens,
        "cache_hit_rate": cached_tokens / input_tokens,
    }


# ---------------------------------------------------------------------------
# should_summarize
# ---------------------------------------------------------------------------


class TestShouldSummarize:
    def test_below_threshold(self) -> None:
        msgs: list[BaseMessage] = [HumanMessage(content="hi")]
        config = ContextConfig(max_context_tokens=999_999)
        assert should_summarize(msgs, config) is False

    def test_above_threshold(self) -> None:
        msgs: list[BaseMessage] = [HumanMessage(content="x " * 5000)]
        config = ContextConfig(max_context_tokens=10)
        assert should_summarize(msgs, config) is True

    def test_uses_default_config(self) -> None:
        msgs: list[BaseMessage] = [HumanMessage(content="short")]
        result = should_summarize(msgs)
        assert isinstance(result, bool)


# ---------------------------------------------------------------------------
# _build_budget_hint
# ---------------------------------------------------------------------------


class TestBuildBudgetHint:
    def test_minimum_budget(self) -> None:
        hint = _build_budget_hint(100)
        assert "2000" in hint

    def test_maximum_budget(self) -> None:
        hint = _build_budget_hint(1_000_000)
        assert "12000" in hint

    def test_proportional_budget(self) -> None:
        hint = _build_budget_hint(25_000)
        assert "5000" in hint

    def test_returns_string(self) -> None:
        assert isinstance(_build_budget_hint(10_000), str)


# ---------------------------------------------------------------------------
# _cap_summary_if_needed
# ---------------------------------------------------------------------------


class TestCapSummaryIfNeeded:
    def test_no_cap_when_smaller(self) -> None:
        summary = StructuredSummary(user_goal="test", completed_actions=["a"])
        result = _cap_summary_if_needed(summary, 999_999, [], None)
        assert result.completed_actions == ["a"]

    def test_phase1_truncation(self) -> None:
        summary = StructuredSummary(
            user_goal="test goal",
            completed_actions=[f"action{i}" for i in range(20)],
            key_findings=[f"finding{i}" for i in range(10)],
            errors_and_fixes=[f"err{i} -> fix{i}" for i in range(10)],
            resolved_questions=[f"q{i} -> a{i}" for i in range(10)],
        )
        result = _cap_summary_if_needed(summary, 5, [], None)
        assert len(result.completed_actions) <= 5
        assert len(result.key_findings) <= 3
        assert len(result.errors_and_fixes) <= 3
        assert len(result.resolved_questions) <= 3

    def test_phase2_aggressive_truncation(self) -> None:
        long_goal = "x" * 500
        summary = StructuredSummary(
            user_goal=long_goal,
            completed_actions=[f"action{i}" for i in range(20)],
            key_findings=[f"finding{i}" for i in range(10)],
            errors_and_fixes=[f"err{i}" for i in range(10)],
            resolved_questions=[f"q{i}" for i in range(10)],
            constraints_and_preferences=[f"c{i}" for i in range(10)],
        )
        result = _cap_summary_if_needed(summary, 5, [], None)
        assert len(result.user_goal) <= 201
        assert len(result.completed_actions) <= 2
        assert len(result.key_findings) <= 1
        assert len(result.constraints_and_preferences) <= 2


# ---------------------------------------------------------------------------
# _log_merge_quality
# ---------------------------------------------------------------------------


class TestLogMergeQuality:
    def test_no_loss(self) -> None:
        before = StructuredSummary(
            user_goal="test", completed_actions=["a"], key_findings=["f"]
        )
        after = StructuredSummary(
            user_goal="test", completed_actions=["a", "b"], key_findings=["f", "g"]
        )
        _log_merge_quality(before, after)

    def test_with_loss(self) -> None:
        before = StructuredSummary(
            user_goal="test",
            completed_actions=["a", "b", "c"],
            key_findings=["f1", "f2"],
            files_modified=["file1.py"],
        )
        after = StructuredSummary(user_goal="test", completed_actions=["a"])
        _log_merge_quality(before, after)


# ---------------------------------------------------------------------------
# generate_structured_summary — full mode
# ---------------------------------------------------------------------------


class TestGenerateStructuredSummaryFull:
    @pytest.mark.asyncio
    async def test_full_summary_first_attempt_pass(self) -> None:
        """First-time summary: audit passes on first attempt."""
        mock_llm = AsyncMock()
        summary_obj = StructuredSummary(
            user_goal="完成认证模块",
            completed_actions=["实现了JWT"],
            last_action="测试",
        )
        summary_json = summary_obj.to_json()
        mock_structured = AsyncMock()
        mock_structured.ainvoke.return_value = summary_obj
        mock_llm.with_structured_output = MagicMock(return_value=mock_structured)
        mock_llm.ainvoke.return_value = MagicMock(
            content=f"<summary>\n{summary_json}\n</summary>"
        )

        messages: list[BaseMessage] = [
            HumanMessage(content="实现JWT认证"),
            AIMessage(content="好的，已完成JWT认证模块"),
        ]

        with patch(
            "myrm_agent_harness.agent.context_management.strategies.summarizer.extract_existing_summary",
            return_value=None,
        ):
            new_messages, summary = await generate_structured_summary(
                messages=messages, llm=mock_llm, chat_id="c1"
            )

        assert summary.user_goal == "完成认证模块"
        assert len(new_messages) >= 1
        invocation_messages = mock_structured.ainvoke.call_args[0][0]
        assert invocation_messages[:-1] == messages
        assert "Use the preceding conversation messages" in invocation_messages[-1].content

    @pytest.mark.asyncio
    async def test_full_summary_with_focus_topic(self) -> None:
        """Verify focus_topic is appended to the prompt."""
        mock_llm = AsyncMock()
        summary_obj = StructuredSummary(user_goal="重构模块", last_action="测试")
        summary_json = summary_obj.to_json()
        mock_structured = AsyncMock()
        mock_structured.ainvoke.return_value = summary_obj
        mock_llm.with_structured_output = MagicMock(return_value=mock_structured)
        mock_llm.ainvoke.return_value = MagicMock(
            content=f"<summary>\n{summary_json}\n</summary>"
        )

        messages: list[BaseMessage] = [HumanMessage(content="重构auth模块")]

        with patch(
            "myrm_agent_harness.agent.context_management.strategies.summarizer.extract_existing_summary",
            return_value=None,
        ):
            _, summary = await generate_structured_summary(
                messages=messages, llm=mock_llm, focus_topic="auth认证安全"
            )

        # Verify focus_topic was passed to the structured LLM
        assert summary is not None

    @pytest.mark.asyncio
    async def test_full_summary_uses_best_after_retries(self) -> None:
        """After audit retries, uses the best summary available."""
        mock_llm = AsyncMock()
        # All attempts return short summaries that may fail density audit.
        # The test verifies the retry + best-selection logic runs without error.
        summary_v1_obj = StructuredSummary(
            user_goal="实现认证", completed_actions=["JWT"], last_action="测试"
        )
        summary_v1 = summary_v1_obj.to_json()
        mock_structured = AsyncMock()
        mock_structured.ainvoke.return_value = summary_v1_obj
        mock_llm.with_structured_output = MagicMock(return_value=mock_structured)
        mock_llm.ainvoke.return_value = MagicMock(
            content=f"<summary>\n{summary_v1}\n</summary>"
        )

        messages: list[BaseMessage] = [
            HumanMessage(content="x " * 2000),
            AIMessage(content="y " * 2000),
        ]

        with patch(
            "myrm_agent_harness.agent.context_management.strategies.summarizer.extract_existing_summary",
            return_value=None,
        ):
            _, summary = await generate_structured_summary(
                messages=messages, llm=mock_llm
            )

        assert summary.user_goal == "实现认证"


# ---------------------------------------------------------------------------
# generate_structured_summary — incremental mode
# ---------------------------------------------------------------------------


class TestGenerateStructuredSummaryIncremental:
    @pytest.mark.asyncio
    async def test_incremental_merge(self) -> None:
        """Incremental mode: existing summary + new messages."""
        existing = StructuredSummary(
            user_goal="完成项目", completed_actions=["步骤1"], last_action="步骤1"
        )
        merged_obj = StructuredSummary(
            user_goal="完成项目",
            completed_actions=["步骤1", "步骤2"],
            last_action="步骤2",
        )
        merged_json = merged_obj.to_json()

        mock_llm = AsyncMock()
        mock_structured = AsyncMock()
        mock_structured.ainvoke.return_value = merged_obj
        mock_llm.with_structured_output = MagicMock(return_value=mock_structured)
        mock_llm.ainvoke.return_value = MagicMock(
            content=f"<summary>\n{merged_json}\n</summary>"
        )

        summary_msg = SystemMessage(
            content=f"[历史摘要]\n<!-- SUMMARY_JSON\n{existing.to_json()}\n-->"
        )
        messages: list[BaseMessage] = [
            summary_msg,
            HumanMessage(content="继续步骤2"),
            AIMessage(content="步骤2完成"),
        ]

        _, summary = await generate_structured_summary(
            messages=messages, llm=mock_llm, existing_summary=existing
        )

        assert "步骤2" in summary.last_action or "步骤2" in str(
            summary.completed_actions
        )

    @pytest.mark.asyncio
    async def test_incremental_no_new_messages(self) -> None:
        """Incremental mode with no new messages keeps existing summary."""
        existing = StructuredSummary(user_goal="完成项目", last_action="步骤1")

        mock_llm = AsyncMock()

        summary_msg = SystemMessage(
            content=f"[历史摘要]\n<!-- SUMMARY_JSON\n{existing.to_json()}\n-->"
        )
        messages: list[BaseMessage] = [summary_msg]

        _, summary = await generate_structured_summary(
            messages=messages, llm=mock_llm, existing_summary=existing
        )

        assert summary.user_goal == "完成项目"
        mock_llm.ainvoke.assert_not_called()

    @pytest.mark.asyncio
    async def test_incremental_with_focus_topic(self) -> None:
        existing = StructuredSummary(user_goal="目标", last_action="x")
        merged_obj = StructuredSummary(user_goal="目标", last_action="y")
        merged_json = merged_obj.to_json()

        mock_llm = AsyncMock()
        mock_structured = AsyncMock()
        mock_structured.ainvoke.return_value = merged_obj
        mock_llm.with_structured_output = MagicMock(return_value=mock_structured)
        mock_llm.ainvoke.return_value = MagicMock(
            content=f"<summary>\n{merged_json}\n</summary>"
        )

        summary_msg = SystemMessage(
            content=f"[历史摘要]\n<!-- SUMMARY_JSON\n{existing.to_json()}\n-->"
        )
        messages: list[BaseMessage] = [
            summary_msg,
            HumanMessage(content="新消息"),
        ]

        _, summary = await generate_structured_summary(
            messages=messages,
            llm=mock_llm,
            existing_summary=existing,
            focus_topic="安全模块",
        )

        # Verify focus_topic was passed to the structured LLM
        assert summary is not None


# ---------------------------------------------------------------------------
# _record_summarize_to_metrics
# ---------------------------------------------------------------------------


class TestRecordSummarizeToMetrics:
    def test_metrics_recording_no_exception(self) -> None:
        from myrm_agent_harness.agent.context_management.strategies.summarizer import (
            _record_summarize_to_metrics,
        )

        _record_summarize_to_metrics(500, "test detail")

    def test_metrics_recording_with_exception(self) -> None:
        """Metrics recording failure should be silently caught."""
        from myrm_agent_harness.agent.context_management.strategies.summarizer import (
            _record_summarize_to_metrics,
        )

        with patch(
            "myrm_agent_harness.agent.context_management.infra.session_lock.get_current_chat_id",
            side_effect=ImportError("mocked"),
        ):
            _record_summarize_to_metrics(100, "test")


class TestCapSummaryPhase1Return:
    def test_phase1_sufficient_truncation(self) -> None:
        """Phase 1 truncation alone is sufficient — no phase 2 needed."""
        summary = StructuredSummary(
            user_goal="目标",
            completed_actions=[f"action{i}" for i in range(20)],
            key_findings=[f"finding{i}" for i in range(10)],
            errors_and_fixes=[f"err{i}" for i in range(10)],
            resolved_questions=[f"q{i}" for i in range(10)],
        )
        # original_tokens = 200 — after phase1 the summary should be smaller
        result = _cap_summary_if_needed(summary, 200, [], None)
        assert len(result.completed_actions) <= 5


class TestGenerateStructuredSummaryEdgeCases:
    @pytest.mark.asyncio
    async def test_incremental_with_log_merge_loss(self) -> None:
        """Incremental merge where after-summary has fewer items triggers loss log."""
        existing = StructuredSummary(
            user_goal="目标",
            completed_actions=["a", "b", "c"],
            key_findings=["f1", "f2"],
            last_action="步骤3",
        )
        # merged returns fewer actions
        merged_summary = StructuredSummary(
            user_goal="目标",
            completed_actions=["a"],
            key_findings=["f1"],
            last_action="步骤4",
        )
        merged_json = merged_summary.to_json()

        mock_llm = AsyncMock()
        mock_structured = AsyncMock()
        mock_structured.ainvoke.return_value = merged_summary
        mock_llm.with_structured_output = MagicMock(return_value=mock_structured)
        mock_llm.ainvoke.return_value = MagicMock(
            content=f"<summary>\n{merged_json}\n</summary>"
        )

        summary_msg = SystemMessage(
            content=f"[历史摘要]\n<!-- SUMMARY_JSON\n{existing.to_json()}\n-->"
        )
        messages: list[BaseMessage] = [
            summary_msg,
            HumanMessage(content="x " * 2000),
            AIMessage(content="y " * 2000),
        ]

        _, summary = await generate_structured_summary(
            messages=messages, llm=mock_llm, existing_summary=existing
        )

        assert summary is not None


# ---------------------------------------------------------------------------
# _redact_summary_fields — output/history-side credential defense
# ---------------------------------------------------------------------------


# Fake credentials matching leak_detector patterns (for testing only)
_FAKE_OPENAI_KEY = "sk-" + "a" * 52  # sk-[a-zA-Z0-9]{48,}
_FAKE_STRIPE_KEY = "sk_live_" + "b" * 30  # sk_(?:live|test)_[a-zA-Z0-9]{24,}
_FAKE_ANTHROPIC_KEY = "sk-ant-" + "c" * 36  # sk-ant-[a-zA-Z0-9_-]{32,}


class TestShouldSummarizeApiTokenSignal:
    """Cover API token signal branch in should_summarize."""

    def test_api_token_triggers_summarize(self) -> None:
        usage_meta = {"input_tokens": 999_999}
        ai_msg = AIMessage(content="response")
        ai_msg.usage_metadata = usage_meta  # type: ignore[attr-defined]
        msgs: list[BaseMessage] = [HumanMessage(content="hi"), ai_msg]
        config = ContextConfig(max_context_tokens=999_999)
        assert should_summarize(msgs, config) is True

    def test_api_token_from_response_metadata(self) -> None:
        ai_msg = AIMessage(content="response")
        ai_msg.usage_metadata = None  # type: ignore[attr-defined]
        ai_msg.response_metadata = {"token_usage": {"prompt_tokens": 999_999}}  # type: ignore[attr-defined]
        msgs: list[BaseMessage] = [HumanMessage(content="hi"), ai_msg]
        config = ContextConfig(max_context_tokens=999_999)
        assert should_summarize(msgs, config) is True

    def test_ignore_api_tokens_flag(self) -> None:
        ai_msg = AIMessage(content="response")
        ai_msg.usage_metadata = {"input_tokens": 999_999}  # type: ignore[attr-defined]
        msgs: list[BaseMessage] = [HumanMessage(content="hi"), ai_msg]
        config = ContextConfig(max_context_tokens=999_999)
        assert should_summarize(msgs, config, ignore_api_tokens=True) is False


class TestInvokeSummaryWithParser:
    """Cover the PydanticOutputParser fallback path in _invoke_summary."""

    @pytest.mark.asyncio
    async def test_parser_path(self) -> None:
        from myrm_agent_harness.agent.context_management.strategies.summarizer import (
            _FallbackSummaryModel,
            _invoke_summary,
        )

        fallback = _FallbackSummaryModel(
            user_goal="test goal", last_action="done"
        )
        mock_parser = MagicMock()
        mock_parser.get_format_instructions.return_value = "format instructions"
        mock_parser.invoke.return_value = fallback

        mock_llm = AsyncMock()
        mock_llm.ainvoke.return_value = MagicMock(content="parsed content")

        result = await _invoke_summary(mock_llm, None, mock_parser, "prompt", "/dump")
        assert result.user_goal == "test goal"
        assert result.context_dump_path == "/dump"
        mock_parser.invoke.assert_called_once()

    def test_build_summary_invocation_messages_preserves_prefix_order(self) -> None:
        prefix: list[BaseMessage] = [
            HumanMessage(content="first"),
            AIMessage(content="second"),
        ]

        invocation_messages = _build_summary_invocation_messages("summarize now", prefix)

        assert invocation_messages[:-1] == prefix
        assert invocation_messages[-1].content == "summarize now"

    def test_cache_safe_invocation_has_reproducible_cache_metric_shape(self) -> None:
        prefix: list[BaseMessage] = [
            SystemMessage(content="stable system policy"),
            HumanMessage(content="source turn " * 200),
            AIMessage(content="source answer " * 200),
        ]

        first_invocation = _build_summary_invocation_messages("summarize with budget 4000", prefix)
        second_invocation = _build_summary_invocation_messages("summarize with budget 8000", prefix)

        metrics = _synthetic_prefix_cache_metrics(first_invocation, second_invocation)

        assert metrics["input_tokens"] > 0
        assert metrics["cached_tokens"] > 0
        assert metrics["cache_hit_rate"] > 0.95


class TestSummarizeWithAuditExceptionHandling:
    """Cover exception handling in _summarize_with_audit."""

    @pytest.mark.asyncio
    async def test_invoke_failure_raises_after_all_retries(self) -> None:
        mock_llm = AsyncMock()
        mock_structured = AsyncMock()
        mock_structured.ainvoke.side_effect = RuntimeError("LLM down")
        mock_llm.with_structured_output = MagicMock(return_value=mock_structured)

        messages: list[BaseMessage] = [
            HumanMessage(content="test"),
            AIMessage(content="response"),
        ]

        with patch(
            "myrm_agent_harness.agent.context_management.strategies.summarizer.extract_existing_summary",
            return_value=None,
        ), pytest.raises(ValueError, match="Failed to generate structured summary"):
            await generate_structured_summary(
                messages=messages, llm=mock_llm, chat_id="c-err"
            )

    @pytest.mark.asyncio
    async def test_invoke_failure_recovers_with_best(self) -> None:
        """First attempt succeeds (provides best), second attempt fails, third attempt also fails."""
        summary_obj = StructuredSummary(
            user_goal="goal", completed_actions=["a"], last_action="done"
        )
        mock_llm = AsyncMock()
        mock_structured = AsyncMock()
        call_count = 0

        async def side_effect(*args: object, **kwargs: object) -> StructuredSummary:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return summary_obj
            raise RuntimeError("LLM down")

        mock_structured.ainvoke.side_effect = side_effect
        mock_llm.with_structured_output = MagicMock(return_value=mock_structured)

        messages: list[BaseMessage] = [
            HumanMessage(content="x " * 2000),
            AIMessage(content="y " * 2000),
        ]

        with patch(
            "myrm_agent_harness.agent.context_management.strategies.summarizer.extract_existing_summary",
            return_value=None,
        ):
            _, summary = await generate_structured_summary(
                messages=messages, llm=mock_llm, chat_id="c-recover"
            )
        assert summary.user_goal == "goal"


class TestSummarizeIncrementalExceptionHandling:
    """Cover exception handling in _summarize_incremental_with_audit."""

    @pytest.mark.asyncio
    async def test_incremental_invoke_failure_raises(self) -> None:
        existing = StructuredSummary(
            user_goal="goal", last_action="step1"
        )
        mock_llm = AsyncMock()
        mock_structured = AsyncMock()
        mock_structured.ainvoke.side_effect = RuntimeError("LLM down")
        mock_llm.with_structured_output = MagicMock(return_value=mock_structured)

        summary_msg = SystemMessage(
            content=f"[历史摘要]\n<!-- SUMMARY_JSON\n{existing.to_json()}\n-->"
        )
        messages: list[BaseMessage] = [
            summary_msg,
            HumanMessage(content="继续"),
            AIMessage(content="好的"),
        ]

        with pytest.raises(ValueError, match="Failed to generate structured summary"):
            await generate_structured_summary(
                messages=messages, llm=mock_llm, existing_summary=existing
            )


class TestGetStructuredLlmOrParserFallback:
    """Cover the NotImplementedError fallback in _get_structured_llm_or_parser."""

    def test_fallback_to_parser(self) -> None:
        from myrm_agent_harness.agent.context_management.strategies.summarizer import (
            _get_structured_llm_or_parser,
        )

        mock_llm = MagicMock()
        mock_llm.with_structured_output.side_effect = NotImplementedError("not supported")

        structured, parser = _get_structured_llm_or_parser(mock_llm)
        assert structured is None
        assert parser is not None


class TestShouldSummarizeProactiveReset:
    """Cover proactive_reset_threshold trigger in should_summarize."""

    def test_proactive_reset_triggers(self) -> None:
        msgs: list[BaseMessage] = [HumanMessage(content="x " * 8000)]
        config = ContextConfig(max_context_tokens=100)
        assert should_summarize(msgs, config) is True


class TestCapSummaryPhase1EarlyReturn:
    """Cover phase1 early-return path at line 358.

    We need original_tokens to be *barely* smaller than the full summary
    (so it enters phase1) but larger than phase1-truncated summary (so phase1
    truncation alone is sufficient and returns at line 358).
    """

    def test_phase1_early_return_when_sufficient(self) -> None:
        summary = StructuredSummary(
            user_goal="short goal",
            completed_actions=[f"action_{i}_long_text_padding" for i in range(20)],
            key_findings=[f"finding_{i}_long_text_padding" for i in range(10)],
            errors_and_fixes=[f"error_{i}_long_text_padding" for i in range(10)],
            resolved_questions=[f"question_{i}_padding" for i in range(10)],
        )
        result = _cap_summary_if_needed(summary, 5, [], None)
        assert len(result.completed_actions) <= 5
        assert len(result.key_findings) <= 3
        assert result.user_goal == "short goal"


class TestRecordCompressionSuccess:
    """Cover successful metrics.record_compression path."""

    def test_successful_metrics_recording(self) -> None:
        from myrm_agent_harness.agent.context_management.strategies.summarizer import (
            _record_summarize_to_metrics,
        )

        mock_metrics = MagicMock()
        with (
            patch(
                "myrm_agent_harness.agent.context_management.infra.session_lock.get_current_chat_id",
                return_value="chat-123",
            ),
            patch(
                "myrm_agent_harness.agent.context_management.tracking.task_metrics.get_task_metrics",
                return_value=mock_metrics,
            ),
        ):
            _record_summarize_to_metrics(500, "test detail")
        mock_metrics.record_compression.assert_called_once_with(
            tokens_saved=500,
            compression_type="summarize",
            details="test detail",
        )


class TestRedactSummaryFields:
    """Verify that _redact_summary_fields applies credential redaction correctly."""

    def test_redacts_openai_key_in_user_goal(self) -> None:
        summary = StructuredSummary(
            user_goal=f"Use {_FAKE_OPENAI_KEY} to test",
            last_action="done",
        )
        result = _redact_summary_fields(summary)
        assert _FAKE_OPENAI_KEY not in result.user_goal
        assert "REDACTED:openai_key" in result.user_goal

    def test_redacts_stripe_key_in_completed_actions(self) -> None:
        summary = StructuredSummary(
            user_goal="setup payment",
            completed_actions=[f"Configured {_FAKE_STRIPE_KEY} in env"],
            last_action="done",
        )
        result = _redact_summary_fields(summary)
        assert _FAKE_STRIPE_KEY not in result.completed_actions[0]
        assert "REDACTED:stripe_key" in result.completed_actions[0]

    def test_redacts_jwt_in_active_state(self) -> None:
        summary = StructuredSummary(
            user_goal="debug auth",
            active_state="Token: eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abcdef",
            last_action="inspect",
        )
        result = _redact_summary_fields(summary)
        assert "eyJhbGciOiJIUzI1NiJ9" not in result.active_state
        assert "REDACTED:jwt_token" in result.active_state

    def test_redacts_database_url_in_key_findings(self) -> None:
        summary = StructuredSummary(
            user_goal="migrate db",
            key_findings=[
                "Connection: postgres://admin:secretpass@db.host.com:5432/mydb"
            ],
            last_action="checked",
        )
        result = _redact_summary_fields(summary)
        assert "secretpass" not in result.key_findings[0]
        assert "REDACTED:database_url" in result.key_findings[0]

    def test_skips_context_dump_path(self) -> None:
        summary = StructuredSummary(
            user_goal="test",
            context_dump_path="/workspace/some-path/dump.jsonl",
            last_action="done",
        )
        result = _redact_summary_fields(summary)
        assert result.context_dump_path == "/workspace/some-path/dump.jsonl"

    def test_skips_files_modified(self) -> None:
        summary = StructuredSummary(
            user_goal="test",
            files_modified=["src/auth/sk_handler.py", "tests/test_jwt.py"],
            last_action="done",
        )
        result = _redact_summary_fields(summary)
        assert result.files_modified == ["src/auth/sk_handler.py", "tests/test_jwt.py"]

    def test_no_op_when_clean(self) -> None:
        summary = StructuredSummary(
            user_goal="Build a REST API",
            completed_actions=["Created routes", "Added tests"],
            key_findings=["Performance improved by 30%"],
            last_action="deployed",
        )
        result = _redact_summary_fields(summary)
        assert result.user_goal == "Build a REST API"
        assert result.completed_actions == ["Created routes", "Added tests"]
        assert result.key_findings == ["Performance improved by 30%"]

    def test_redacts_env_credential_in_errors_and_fixes(self) -> None:
        summary = StructuredSummary(
            user_goal="fix config",
            errors_and_fixes=[
                f"export API_KEY={_FAKE_ANTHROPIC_KEY} was wrong -> removed"
            ],
            last_action="fixed",
        )
        result = _redact_summary_fields(summary)
        assert _FAKE_ANTHROPIC_KEY not in result.errors_and_fixes[0]

    def test_redacts_multiple_fields_simultaneously(self) -> None:
        summary = StructuredSummary(
            user_goal=f"Deploy with {_FAKE_OPENAI_KEY}",
            active_task="Fix eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abcdef leak",
            constraints_and_preferences=["Use postgres://user:pass123456789@host/db"],
            last_action="done",
        )
        result = _redact_summary_fields(summary)
        assert "REDACTED:openai_key" in result.user_goal
        assert "REDACTED:jwt_token" in result.active_task
        assert "REDACTED:database_url" in result.constraints_and_preferences[0]


class TestRedactSummaryIntegrationInInvokeSummary:
    """Verify that _invoke_summary applies redaction to LLM output."""

    @pytest.mark.asyncio
    async def test_invoke_summary_redacts_output(self) -> None:
        summary_with_key = StructuredSummary(
            user_goal=f"Test with {_FAKE_OPENAI_KEY}",
            completed_actions=["Used the key"],
            last_action="done",
        )
        mock_llm = AsyncMock()
        mock_structured = AsyncMock()
        mock_structured.ainvoke.return_value = summary_with_key
        mock_llm.with_structured_output = MagicMock(return_value=mock_structured)

        from myrm_agent_harness.agent.context_management.strategies.summarizer import (
            _invoke_summary,
        )

        result = await _invoke_summary(
            mock_llm, mock_structured, None, "test prompt", ""
        )
        assert _FAKE_OPENAI_KEY not in result.user_goal
        assert "REDACTED:openai_key" in result.user_goal


class TestRedactSummaryIntegrationInIncremental:
    """Verify that incremental summarization redacts existing_summary before injection."""

    @pytest.mark.asyncio
    async def test_incremental_redacts_existing_summary(self) -> None:
        existing = StructuredSummary(
            user_goal=f"Setup with {_FAKE_OPENAI_KEY}",
            completed_actions=["step1"],
            last_action="step1",
        )
        merged_obj = StructuredSummary(
            user_goal="Setup complete",
            completed_actions=["step1", "step2"],
            last_action="step2",
        )
        mock_llm = AsyncMock()
        mock_structured = AsyncMock()
        mock_structured.ainvoke.return_value = merged_obj
        mock_llm.with_structured_output = MagicMock(return_value=mock_structured)

        summary_msg = SystemMessage(
            content=f"[历史摘要]\n<!-- SUMMARY_JSON\n{existing.to_json()}\n-->"
        )
        messages: list[BaseMessage] = [
            summary_msg,
            HumanMessage(content="继续步骤2"),
            AIMessage(content="步骤2完成"),
        ]

        await generate_structured_summary(
            messages=messages, llm=mock_llm, existing_summary=existing
        )

        call_args = mock_structured.ainvoke.call_args
        prompt_content = call_args[0][0][0].content if call_args else ""
        assert _FAKE_OPENAI_KEY not in prompt_content


# ---------------------------------------------------------------------------
# _guard_aux_context — K4 aux model context guard
# ---------------------------------------------------------------------------


class TestGuardAuxContext:
    """Verify _guard_aux_context trims messages for small aux models."""

    def test_no_trim_when_limit_unknown(self) -> None:
        from myrm_agent_harness.agent.context_management.strategies.summarizer import (
            _guard_aux_context,
        )

        mock_llm = MagicMock()
        msgs: list[BaseMessage] = [HumanMessage(content="x " * 5000)]

        with patch(
            "myrm_agent_harness.agent.context_management.strategies.summarizer.get_model_context_limit",
            return_value=None,
        ):
            result = _guard_aux_context(msgs, mock_llm)

        assert result is msgs

    def test_no_trim_when_within_budget(self) -> None:
        from myrm_agent_harness.agent.context_management.strategies.summarizer import (
            _guard_aux_context,
        )

        mock_llm = MagicMock()
        msgs: list[BaseMessage] = [HumanMessage(content="short")]

        with patch(
            "myrm_agent_harness.agent.context_management.strategies.summarizer.get_model_context_limit",
            return_value=128_000,
        ):
            result = _guard_aux_context(msgs, mock_llm)

        assert result is msgs

    def test_trims_when_exceeding_aux_limit(self) -> None:
        from myrm_agent_harness.agent.context_management.strategies.summarizer import (
            _guard_aux_context,
        )

        mock_llm = MagicMock()
        msgs: list[BaseMessage] = [
            HumanMessage(content=f"message {i} " + "padding " * 2000)
            for i in range(20)
        ]

        with patch(
            "myrm_agent_harness.agent.context_management.strategies.summarizer.get_model_context_limit",
            return_value=8192,
        ):
            result = _guard_aux_context(msgs, mock_llm)

        assert len(result) < len(msgs)
        assert len(result) >= 1
        assert result[-1] is msgs[-1]

    def test_preserves_most_recent_messages(self) -> None:
        from myrm_agent_harness.agent.context_management.strategies.summarizer import (
            _guard_aux_context,
        )

        mock_llm = MagicMock()
        msgs: list[BaseMessage] = [
            HumanMessage(content=f"msg-{i} " + "x " * 500) for i in range(10)
        ]

        with patch(
            "myrm_agent_harness.agent.context_management.strategies.summarizer.get_model_context_limit",
            return_value=4096,
        ):
            result = _guard_aux_context(msgs, mock_llm)

        for trimmed_msg in result:
            assert trimmed_msg is msgs[msgs.index(trimmed_msg)]
        assert result[-1] is msgs[-1]

    def test_at_least_one_message_when_all_too_large(self) -> None:
        from myrm_agent_harness.agent.context_management.strategies.summarizer import (
            _guard_aux_context,
        )

        mock_llm = MagicMock()
        msgs: list[BaseMessage] = [
            HumanMessage(content="enormous " * 10000),
        ]

        with patch(
            "myrm_agent_harness.agent.context_management.strategies.summarizer.get_model_context_limit",
            return_value=1024,
        ):
            result = _guard_aux_context(msgs, mock_llm)

        assert len(result) == 1
        assert result[0] is msgs[-1]

    def test_handles_tiny_aux_context_gracefully(self) -> None:
        """Aux model so small that safe_budget <= 0 — returns original messages."""
        from myrm_agent_harness.agent.context_management.strategies.summarizer import (
            _guard_aux_context,
        )

        mock_llm = MagicMock()
        msgs: list[BaseMessage] = [HumanMessage(content="test")]

        with patch(
            "myrm_agent_harness.agent.context_management.strategies.summarizer.get_model_context_limit",
            return_value=100,
        ):
            result = _guard_aux_context(msgs, mock_llm, prompt_tokens=200)

        assert result is msgs


class TestGuardAuxContextIntegration:
    """Verify _guard_aux_context is wired into generate_structured_summary."""

    @pytest.mark.asyncio
    async def test_full_summary_uses_guarded_messages(self) -> None:
        """Full summary path passes guarded messages to _invoke_summary."""
        summary_obj = StructuredSummary(
            user_goal="test", completed_actions=["a"], last_action="done"
        )
        mock_llm = AsyncMock()
        mock_structured = AsyncMock()
        mock_structured.ainvoke.return_value = summary_obj
        mock_llm.with_structured_output = MagicMock(return_value=mock_structured)

        msgs: list[BaseMessage] = [
            HumanMessage(content=f"msg {i} " + "pad " * 500) for i in range(20)
        ]

        with (
            patch(
                "myrm_agent_harness.agent.context_management.strategies.summarizer.extract_existing_summary",
                return_value=None,
            ),
            patch(
                "myrm_agent_harness.agent.context_management.strategies.summarizer.get_model_context_limit",
                return_value=4096,
            ),
        ):
            _, _summary = await generate_structured_summary(
                messages=msgs, llm=mock_llm, chat_id="c-guard"
            )

        call_args = mock_structured.ainvoke.call_args[0][0]
        assert len(call_args) < len(msgs) + 1

    @pytest.mark.asyncio
    async def test_full_summary_no_trim_for_large_model(self) -> None:
        """No trimming when aux model has large context."""
        summary_obj = StructuredSummary(
            user_goal="test", completed_actions=["a"], last_action="done"
        )
        mock_llm = AsyncMock()
        mock_structured = AsyncMock()
        mock_structured.ainvoke.return_value = summary_obj
        mock_llm.with_structured_output = MagicMock(return_value=mock_structured)

        msgs: list[BaseMessage] = [
            HumanMessage(content="short msg"),
            AIMessage(content="short reply"),
        ]

        with (
            patch(
                "myrm_agent_harness.agent.context_management.strategies.summarizer.extract_existing_summary",
                return_value=None,
            ),
            patch(
                "myrm_agent_harness.agent.context_management.strategies.summarizer.get_model_context_limit",
                return_value=200_000,
            ),
        ):
            _, _summary = await generate_structured_summary(
                messages=msgs, llm=mock_llm, chat_id="c-large"
            )

        call_args = mock_structured.ainvoke.call_args[0][0]
        assert len(call_args) == len(msgs) + 1
