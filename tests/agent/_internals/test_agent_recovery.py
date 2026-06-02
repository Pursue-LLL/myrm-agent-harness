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
            "myrm_agent_harness.agent.context_management.strategies.compactor.compress_messages_async",
            new_callable=AsyncMock,
            return_value=(msgs, 500),
        ) as mock_compress:
            saved = await emergency_compact(msgs)
            assert saved == 500
            mock_compress.assert_called_once()


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
