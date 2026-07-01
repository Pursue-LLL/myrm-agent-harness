"""Unit tests for executor_helpers (fork filter, error compaction, vault edge cases)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from myrm_agent_harness.agent.sub_agents.executor_helpers import (
    _auto_vault_or_truncate,
    _cascade_cancel_descendants,
    _compact_error_message,
    _estimate_msg_tokens,
    _filter_fork_messages,
    _parse_handover_state,
)
from myrm_agent_harness.agent.sub_agents.types import SubagentConfig


class TestFilterForkMessages:
    def test_strips_tool_messages_and_empty_ai(self) -> None:
        msgs = [
            SystemMessage(content="sys"),
            HumanMessage(content="hi"),
            AIMessage(content="answer", tool_calls=[{"id": "1", "name": "t", "args": {}}]),
            AIMessage(content=""),
            ToolMessage(content="tool out", tool_call_id="1"),
        ]
        filtered = _filter_fork_messages(msgs)
        assert len(filtered) == 3
        assert isinstance(filtered[2], AIMessage)
        assert not getattr(filtered[2], "tool_calls", None)

    def test_truncates_by_token_budget(self) -> None:
        msgs = [
            SystemMessage(content="sys"),
            HumanMessage(content="a" * 400),
            HumanMessage(content="b" * 400),
        ]
        filtered = _filter_fork_messages(msgs, max_fork_tokens=50)
        assert isinstance(filtered[0], SystemMessage)
        assert len(filtered) >= 1
        total = sum(_estimate_msg_tokens(m) for m in filtered)
        assert total <= 50 or len(filtered) == 1


class TestEstimateMsgTokens:
    def test_string_content(self) -> None:
        assert _estimate_msg_tokens(HumanMessage(content="abcd")) >= 1

    def test_list_content(self) -> None:
        msg = HumanMessage(content=[{"type": "text", "text": "hello world"}])
        assert _estimate_msg_tokens(msg) >= 1

    def test_unknown_content_defaults_to_one(self) -> None:
        assert _estimate_msg_tokens(object()) == 1


class TestCompactErrorMessage:
    def test_short_error_unchanged(self) -> None:
        assert _compact_error_message("err", 100) == "err"

    def test_long_error_compacted(self) -> None:
        err = "E" * 200 + "TAIL"
        out = _compact_error_message(err, 80)
        assert "truncated" in out
        assert out.endswith("TAIL")

    def test_zero_max_chars_returns_prefix(self) -> None:
        err = "abcdefghij"
        assert _compact_error_message(err, 0) == err


class TestCascadeCancelDescendants:
    def test_none_agent_is_noop(self) -> None:
        _cascade_cancel_descendants(None)

    def test_cancels_children(self) -> None:
        child = MagicMock()
        child.cancel_all_children.return_value = 2
        _cascade_cancel_descendants(child)
        child.cancel_all_children.assert_called_once()

    def test_swallows_cancel_errors(self) -> None:
        child = MagicMock()
        child.cancel_all_children.side_effect = RuntimeError("boom")
        _cascade_cancel_descendants(child)


class TestAutoVaultEdgeCases:
    @pytest.fixture
    def config(self) -> SubagentConfig:
        return SubagentConfig(system_prompt="t", auto_vault_threshold=50, max_result_tokens=20)

    def test_vault_failure_falls_back_to_truncation(self, config: SubagentConfig, tmp_path) -> None:
        ws = str(tmp_path)
        with patch(
            "myrm_agent_harness.agent.artifacts.vault.ArtifactVault.put",
            side_effect=OSError("disk full"),
        ):
            result = _auto_vault_or_truncate("x" * 100, config, {"workspace_path": ws}, "t1", "agent")
        assert "vault://" not in result

    def test_inline_artifact_failure_still_vaults(self, config: SubagentConfig, tmp_path) -> None:
        ws = str(tmp_path)
        with patch(
            "myrm_agent_harness.agent.sub_agents.executor_helpers.push_inline_artifact",
            side_effect=RuntimeError("no context"),
        ):
            result = _auto_vault_or_truncate("y" * 100, config, {"workspace_path": ws}, "t2", "agent")
        assert "vault://" in result

    def test_short_vaulted_result_no_omitted_marker(self, config: SubagentConfig, tmp_path) -> None:
        ws = str(tmp_path)
        payload = "z" * 80
        result = _auto_vault_or_truncate(payload, config, {"workspace_path": ws}, "t3", "agent")
        assert "vault://" in result
        assert "chars omitted" not in result


class TestParseHandoverStateFences:
    def test_handover_with_plain_fence(self) -> None:
        raw = '<handover>```\n{"status": "ok"}\n```</handover>'
        state = _parse_handover_state(raw, "t1")
        assert state is not None
