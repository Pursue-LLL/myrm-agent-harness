"""Tests for agent._internals.agent_recovery — recovery strategies."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

# ============================================================================
# truncate_oldest_rounds
# ============================================================================


class TestTruncateOldestRounds:
    """Tests for truncate_oldest_rounds — drops oldest API-round groups."""

    def test_empty_messages(self):
        from myrm_agent_harness.agent._internals.agent_recovery import truncate_oldest_rounds

        msgs: list[BaseMessage] = []
        freed = truncate_oldest_rounds(msgs)
        assert freed == 0
        assert msgs == []

    def test_only_system_messages(self):
        from myrm_agent_harness.agent._internals.agent_recovery import truncate_oldest_rounds

        msgs: list[BaseMessage] = [SystemMessage(content="sys1"), SystemMessage(content="sys2")]
        freed = truncate_oldest_rounds(msgs)
        assert freed == 0
        assert len(msgs) == 2

    def test_single_group_not_truncated(self):
        from myrm_agent_harness.agent._internals.agent_recovery import truncate_oldest_rounds

        msgs: list[BaseMessage] = [
            SystemMessage(content="sys"),
            HumanMessage(content="hello"),
            AIMessage(content="hi"),
        ]
        freed = truncate_oldest_rounds(msgs)
        assert freed == 0
        assert len(msgs) == 3

    def test_multiple_groups_truncated(self):
        from myrm_agent_harness.agent._internals.agent_recovery import truncate_oldest_rounds

        msgs: list[BaseMessage] = [
            SystemMessage(content="sys"),
            HumanMessage(content="q1"),
            AIMessage(content="a1"),
            HumanMessage(content="q2"),
            AIMessage(content="a2"),
            HumanMessage(content="q3"),
            AIMessage(content="a3"),
        ]
        original_len = len(msgs)
        freed = truncate_oldest_rounds(msgs)

        assert freed > 0
        assert len(msgs) < original_len
        assert isinstance(msgs[0], SystemMessage)
        assert msgs[0].content == "sys"
        # Truncation marker should be present
        assert any("[earlier conversation truncated" in str(m.content) for m in msgs)

    def test_preserves_system_prefix(self):
        from myrm_agent_harness.agent._internals.agent_recovery import truncate_oldest_rounds

        sys1 = SystemMessage(content="system prompt")
        sys2 = SystemMessage(content="extra system")
        msgs: list[BaseMessage] = [
            sys1,
            sys2,
            HumanMessage(content="q1"),
            AIMessage(content="a1"),
            HumanMessage(content="q2"),
            AIMessage(content="a2"),
        ]
        truncate_oldest_rounds(msgs)
        assert msgs[0] is sys1
        assert msgs[1] is sys2

    def test_no_system_prefix(self):
        from myrm_agent_harness.agent._internals.agent_recovery import truncate_oldest_rounds

        msgs: list[BaseMessage] = [
            HumanMessage(content="q1"),
            AIMessage(content="a1"),
            HumanMessage(content="q2"),
            AIMessage(content="a2"),
            HumanMessage(content="q3"),
            AIMessage(content="a3"),
        ]
        freed = truncate_oldest_rounds(msgs)
        assert freed > 0
        assert any("[earlier conversation truncated" in str(m.content) for m in msgs)


# ============================================================================
# emergency_compact
# ============================================================================


class TestEmergencyCompact:
    @pytest.mark.asyncio
    async def test_calls_compress(self):
        from myrm_agent_harness.agent._internals.agent_recovery import emergency_compact

        msgs: list[BaseMessage] = [
            SystemMessage(content="sys"),
            HumanMessage(content="hello"),
            AIMessage(content="hi"),
        ]

        with patch(
            "myrm_agent_harness.agent.context_management.strategies.compactor.compactor.compress_messages_async",
            new_callable=AsyncMock,
            return_value=(msgs, 500),
        ) as mock_compress:
            saved = await emergency_compact(msgs)
            assert saved == 500
            mock_compress.assert_called_once()

    @pytest.mark.asyncio
    async def test_emergency_compact_integrates_active_prune_phase1(self):
        from langchain_core.messages import ToolMessage
        from myrm_agent_harness.agent._internals.agent_recovery import emergency_compact

        large_output = "data " * 5000  # ~5000 tokens
        msgs: list[BaseMessage] = [
            HumanMessage(content="run task"),
            AIMessage(
                content="running...",
                tool_calls=[{"id": "tc1", "name": "grep_tool", "args": {}}],
            ),
            ToolMessage(content=large_output, name="grep_tool", tool_call_id="tc1"),
            AIMessage(
                content="next step...",
                tool_calls=[{"id": "tc2", "name": "web_search", "args": {}}],
            ),
            ToolMessage(content="ok", name="web_search", tool_call_id="tc2"),
        ]

        with patch(
            "myrm_agent_harness.agent.context_management.strategies.compactor.compactor.compress_messages_async",
            new_callable=AsyncMock,
            return_value=(msgs, 100),
        ) as mock_compress:
            saved = await emergency_compact(msgs)
            # Active prune saved ~4900 tokens + compactor saved 100
            assert saved > 4000
            mock_compress.assert_called_once()
            # Ensure the large tool message was truncated with emergency_recovery reason
            assert "[Tool output pruned: original size" in str(msgs[2].content)
            assert "emergency_recovery" in str(msgs[2].content)



# ============================================================================
# _extract_error_type
# ============================================================================


class TestExtractErrorType:
    def test_standard_error(self):
        from myrm_agent_harness.agent._internals.agent_recovery import _extract_error_type

        assert _extract_error_type("FileNotFoundError: No such file") == "FileNotFoundError"

    def test_permission_error(self):
        from myrm_agent_harness.agent._internals.agent_recovery import _extract_error_type

        assert _extract_error_type("PermissionError: Access denied") == "PermissionError"

    def test_no_match(self):
        from myrm_agent_harness.agent._internals.agent_recovery import _extract_error_type

        assert _extract_error_type("Something went wrong") == "UnknownError"

    def test_empty_string(self):
        from myrm_agent_harness.agent._internals.agent_recovery import _extract_error_type

        assert _extract_error_type("") == "UnknownError"

    def test_nested_error(self):
        from myrm_agent_harness.agent._internals.agent_recovery import _extract_error_type

        assert _extract_error_type("ConnectionError: timeout after 30s") == "ConnectionError"


# ============================================================================
# build_error_context
# ============================================================================


class TestBuildErrorContext:
    def test_basic_output(self):
        from myrm_agent_harness.agent._internals.agent_recovery import build_error_context

        result = build_error_context(
            operation="file_read",
            target="/tmp/test.txt",
            error="FileNotFoundError: No such file",
        )
        assert "## Error Recovery Context" in result
        assert "file_read" in result
        assert "/tmp/test.txt" in result
        assert "FileNotFoundError" in result
        assert "Verify the file path" in result

    def test_with_previous_attempts(self):
        from myrm_agent_harness.agent._internals.agent_recovery import build_error_context

        result = build_error_context(
            operation="web_fetch",
            target="https://example.com",
            error="ConnectionError: refused",
            previous_attempts=["Tried HTTP", "Tried HTTPS"],
        )
        assert "Previous Attempts" in result
        assert "Tried HTTP" in result
        assert "Tried HTTPS" in result
        assert "(2)" in result

    def test_unknown_error_type_gets_generic_hints(self):
        from myrm_agent_harness.agent._internals.agent_recovery import build_error_context

        result = build_error_context(
            operation="custom_op",
            target="target",
            error="WeirdProblem: something broke",
        )
        assert "Analyse the error message" in result

    def test_known_error_types_get_specific_hints(self):
        from myrm_agent_harness.agent._internals.agent_recovery import ERROR_RECOVERY_HINTS, build_error_context

        for error_type in ERROR_RECOVERY_HINTS:
            result = build_error_context(
                operation="test",
                target="test",
                error=f"{error_type}: test error",
            )
            expected_hint = ERROR_RECOVERY_HINTS[error_type][0]
            assert expected_hint in result, f"Expected hint for {error_type} not found"


# ============================================================================
# diagnose_llm_error
# ============================================================================


class TestDiagnoseLlmError:
    def test_returns_tuple(self):
        from myrm_agent_harness.agent._internals.agent_recovery import diagnose_llm_error

        llm = MagicMock()
        llm.model_name = "test-model"
        llm.base_url = None

        msg, _diagnostic = diagnose_llm_error(ValueError("test"), llm, None)
        assert isinstance(msg, str)
        assert len(msg) > 0

    def test_graceful_on_diagnostic_failure(self):
        from myrm_agent_harness.agent._internals.agent_recovery import diagnose_llm_error

        llm = MagicMock()
        llm.model_name = "test-model"
        llm.base_url = None

        with patch(
            "myrm_agent_harness.agent.errors.diagnostics.LLMErrorDiagnostic.diagnose",
            side_effect=Exception("mock diagnostic fail"),
        ):
            msg, diagnostic = diagnose_llm_error(RuntimeError("boom"), llm, None)
            assert isinstance(msg, str)
            assert diagnostic is None

    def test_diagnose_prefers_api_base_over_base_url(self):
        from types import SimpleNamespace

        from myrm_agent_harness.agent._internals.agent_recovery import diagnose_llm_error
        from myrm_agent_harness.agent.errors.diagnostics import (
            DiagnosticResult,
            ErrorContext,
        )

        llm = SimpleNamespace(
            model_name="test-model",
            model="test-model",
            api_base="https://custom.example.com/v1",
            base_url="https://legacy.example.com/v1",
        )

        captured: dict[str, ErrorContext] = {}

        def _capture_diagnose(
            _exc: Exception,
            ctx: ErrorContext,
            locale: str | None = None,
            cooldown_remaining_ms: int | None = None,
        ) -> DiagnosticResult:
            captured["ctx"] = ctx
            return DiagnosticResult(
                error_type="test",
                user_message="user msg",
                resolution_steps=["step1"],
                is_retryable=False,
                locale=locale or "en",
            )

        with patch(
            "myrm_agent_harness.agent.errors.diagnostics.LLMErrorDiagnostic.diagnose",
            side_effect=_capture_diagnose,
        ):
            msg, diagnostic = diagnose_llm_error(RuntimeError("boom"), llm, None)  # type: ignore[arg-type]

        ctx = captured["ctx"]
        assert ctx.base_url == "https://custom.example.com/v1"
        assert ctx.is_custom_endpoint is True
        assert isinstance(msg, str)
        assert diagnostic is not None
        assert diagnostic["user_message"] == "user msg"


# ============================================================================
# rebuild_agent_with_llm
# ============================================================================


class TestRebuildAgentWithLlm:
    def test_replaces_llm_and_rebuilds(self):
        from myrm_agent_harness.agent._internals.agent_recovery import rebuild_agent_with_llm

        agent = MagicMock()
        agent._apply_parallel_tool_calls.return_value = MagicMock()
        agent._cached_tools = [MagicMock()]
        agent._cached_system_prompt = "sys"
        agent._cached_middlewares = []
        agent.context_schema = None
        agent.checkpointer = None

        new_llm = MagicMock()

        with patch("langchain.agents.create_agent") as mock_create:
            mock_create.return_value = MagicMock()
            rebuild_agent_with_llm(agent, new_llm)

            assert agent.llm == new_llm
            mock_create.assert_called_once()
            call_kwargs = mock_create.call_args
            assert call_kwargs.kwargs["tools"] == agent._cached_tools
            assert call_kwargs.kwargs["system_prompt"] == "sys"

    def test_stops_old_keepalive_on_rebuild(self):
        """rebuild_agent_with_llm should stop old keepalive and start new one
        when failing over to another explicit-cache provider."""
        from myrm_agent_harness.agent._internals.agent_recovery import rebuild_agent_with_llm

        agent = MagicMock()
        agent._apply_parallel_tool_calls.return_value = MagicMock()
        agent._cached_tools = [MagicMock()]
        agent._cached_system_prompt = "sys"
        agent._cached_middlewares = []
        agent.context_schema = None
        agent.checkpointer = None

        old_keepalive = MagicMock()
        agent._cache_keepalive = old_keepalive

        new_llm = MagicMock()
        new_llm.model_name = "anthropic/claude-3-5-sonnet"

        with (
            patch("langchain.agents.create_agent", return_value=MagicMock()),
            patch(
                "myrm_agent_harness.agent.context_management.preheat.needs_explicit_preheat",
                return_value=True,
            ),
            patch("myrm_agent_harness.agent.context_management.preheat.CacheKeepAliveManager") as MockKAM,  # noqa: N806 mock 类名别名
        ):
            new_kam_instance = MagicMock()
            MockKAM.return_value = new_kam_instance

            rebuild_agent_with_llm(agent, new_llm)

            old_keepalive.stop.assert_called_once()
            MockKAM.assert_called_once_with(new_llm, "sys", "anthropic/claude-3-5-sonnet")
            new_kam_instance.start.assert_called_once()
            assert agent._cache_keepalive == new_kam_instance

    def test_no_new_keepalive_for_auto_cache_provider(self):
        """rebuild_agent_with_llm should not start keepalive for providers
        that use automatic caching (e.g., OpenAI, DeepSeek)."""
        from myrm_agent_harness.agent._internals.agent_recovery import rebuild_agent_with_llm

        agent = MagicMock()
        agent._apply_parallel_tool_calls.return_value = MagicMock()
        agent._cached_tools = [MagicMock()]
        agent._cached_system_prompt = "sys"
        agent._cached_middlewares = []
        agent.context_schema = None
        agent.checkpointer = None

        old_keepalive = MagicMock()
        agent._cache_keepalive = old_keepalive

        new_llm = MagicMock()
        new_llm.model_name = "gpt-4o"

        with (
            patch("langchain.agents.create_agent", return_value=MagicMock()),
            patch(
                "myrm_agent_harness.agent.context_management.preheat.needs_explicit_preheat",
                return_value=False,
            ),
        ):
            rebuild_agent_with_llm(agent, new_llm)

            old_keepalive.stop.assert_called_once()
            assert agent._cache_keepalive is None

    def test_rebuild_without_existing_keepalive(self):
        """rebuild_agent_with_llm should create keepalive from scratch when
        the agent had none (e.g., originally on auto-cache provider)."""
        from myrm_agent_harness.agent._internals.agent_recovery import rebuild_agent_with_llm

        agent = MagicMock()
        agent._apply_parallel_tool_calls.return_value = MagicMock()
        agent._cached_tools = [MagicMock()]
        agent._cached_system_prompt = "sys"
        agent._cached_middlewares = []
        agent.context_schema = None
        agent.checkpointer = None
        agent._cache_keepalive = None

        new_llm = MagicMock()
        new_llm.model_name = "anthropic/claude-3-5-sonnet"

        with (
            patch("langchain.agents.create_agent", return_value=MagicMock()),
            patch(
                "myrm_agent_harness.agent.context_management.preheat.needs_explicit_preheat",
                return_value=True,
            ),
            patch("myrm_agent_harness.agent.context_management.preheat.CacheKeepAliveManager") as MockKAM,  # noqa: N806 mock 类名别名
        ):
            new_kam_instance = MagicMock()
            MockKAM.return_value = new_kam_instance

            rebuild_agent_with_llm(agent, new_llm)

            MockKAM.assert_called_once()
            new_kam_instance.start.assert_called_once()
            assert agent._cache_keepalive == new_kam_instance
