"""Unit tests for HITL correction learning hook.

Tests cover:
- Signal extraction from approval edits
- Signal classification (path_preference, command_rule, arg_preference)
- Memory creation (SemanticMemory for preferences, ProceduralMemory for rules)
- Deduplication within a session
- Summary generation for frontend feedback
- Edge cases (empty payloads, malformed data, no memory manager)
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from unittest.mock import AsyncMock, patch

import pytest

from myrm_agent_harness.agent.middlewares.approval.correction_learning import (
    CorrectionLearningHook,
    CorrectionSignal,
    _format_value,
)
from myrm_agent_harness.toolkits.memory.types import (
    ProceduralMemory,
    SemanticMemory,
    ToolRulePriority,
)


@pytest.fixture
def hook() -> CorrectionLearningHook:
    return CorrectionLearningHook()


def _edit(tool_name: str, original: dict[str, object], edited: dict[str, object]) -> dict[str, object]:
    return {"tool_name": tool_name, "original_args": original, "edited_args": edited}


class TestSignalExtraction:
    """Tests for _extract_signals classification logic."""

    def test_edit_path_preference(self, hook: CorrectionLearningHook) -> None:
        signals = hook._extract_signals(
            [
                _edit(
                    "write_file",
                    {"path": "/tmp/test.py", "content": "x=1"},
                    {"path": "/home/user/test.py", "content": "x=1"},
                )
            ]
        )
        assert len(signals) == 1
        assert signals[0].signal_class == "path_preference"
        assert signals[0].tool_name == "write_file"
        assert signals[0].arg_key == "path"
        assert signals[0].original_value == "/tmp/test.py"
        assert signals[0].corrected_value == "/home/user/test.py"

    def test_edit_command_rule(self, hook: CorrectionLearningHook) -> None:
        signals = hook._extract_signals([_edit("shell", {"command": "rm -rf /tmp/old"}, {"command": "rm -r /tmp/old"})])
        assert len(signals) == 1
        assert signals[0].signal_class == "command_rule"
        assert signals[0].arg_key == "command"

    def test_edit_arg_preference(self, hook: CorrectionLearningHook) -> None:
        signals = hook._extract_signals(
            [
                _edit(
                    "web_search",
                    {"query": "python tutorial", "max_results": 5},
                    {"query": "python tutorial", "max_results": 10},
                )
            ]
        )
        assert len(signals) == 1
        assert signals[0].signal_class == "arg_preference"
        assert signals[0].arg_key == "max_results"
        assert signals[0].original_value == 5
        assert signals[0].corrected_value == 10

    def test_multiple_arg_changes_in_single_correction(self, hook: CorrectionLearningHook) -> None:
        signals = hook._extract_signals(
            [
                _edit(
                    "write_file",
                    {"path": "/tmp/a.txt", "content": "old"},
                    {"path": "/home/user/a.txt", "content": "new"},
                )
            ]
        )
        assert len(signals) == 2
        classes = {s.signal_class for s in signals}
        assert "path_preference" in classes
        assert "arg_preference" in classes

    def test_unchanged_args_ignored(self, hook: CorrectionLearningHook) -> None:
        same = {"path": "/home/user/a.txt", "content": "same"}
        assert hook._extract_signals([_edit("write_file", same, dict(same))]) == []

    def test_malformed_correction_skipped(self, hook: CorrectionLearningHook) -> None:
        corrections = [
            {"tool_name": "", "original_args": {"a": 1}, "edited_args": {"a": 2}},
            {"original_args": {"a": 1}, "edited_args": {"a": 2}},
            {"tool_name": "x", "original_args": None, "edited_args": {"a": 2}},
            {"tool_name": "x", "original_args": {"a": 1}, "edited_args": None},
            "not a dict",
            None,
        ]
        assert hook._extract_signals(corrections) == []


class TestMemoryCreation:
    """Tests for memory object creation from signals."""

    def test_path_preference_creates_semantic_memory(self, hook: CorrectionLearningHook) -> None:
        signal = CorrectionSignal(
            tool_name="write_file",
            arg_key="path",
            original_value="/tmp/test.py",
            corrected_value="/home/user/test.py",
            signal_class="path_preference",
        )
        memory = hook._create_memory(signal)
        assert isinstance(memory, SemanticMemory)
        assert "prefer path" in memory.content
        assert "/home/user/test.py" in memory.content
        assert memory.preference_type == "explicit"
        assert abs(memory.preference_strength - 0.8) < 0.01
        assert "hitl_correction" in memory.tags
        assert "tool:write_file" in memory.tags

    def test_command_rule_creates_procedural_memory(self, hook: CorrectionLearningHook) -> None:
        signal = CorrectionSignal(
            tool_name="shell",
            arg_key="command",
            original_value="rm -rf /",
            corrected_value="rm -r /tmp/old",
            signal_class="command_rule",
        )
        memory = hook._create_memory(signal)
        assert isinstance(memory, ProceduralMemory)
        assert "rm -r /tmp/old" in memory.content
        assert memory.tool_name == "shell"
        assert memory.tool_rule_priority == ToolRulePriority.NORMAL


class TestDeduplication:
    """Tests for session-level deduplication."""

    @pytest.mark.asyncio
    async def test_same_correction_deduped_in_session(self, hook: CorrectionLearningHook) -> None:
        payload = {
            "session_id": "test-session",
            "corrections": (_edit("write_file", {"path": "/tmp/a.txt"}, {"path": "/home/user/a.txt"}),),
        }

        with patch(
            "myrm_agent_harness.agent.skill_agent.context.get_memory_manager",
            return_value=None,
        ):
            result1 = await hook.on_approval_correction("approval_correction", payload)
            result2 = await hook.on_approval_correction("approval_correction", payload)

        assert result1.output is not None and result1.output != ""
        assert result2.output is None or result2.output == ""

    @pytest.mark.asyncio
    async def test_different_tools_not_deduped(self, hook: CorrectionLearningHook) -> None:
        payload1 = {
            "session_id": "test-session",
            "corrections": (_edit("write_file", {"path": "/tmp/a.txt"}, {"path": "/home/user/a.txt"}),),
        }
        payload2 = {
            "session_id": "test-session",
            "corrections": (_edit("read_file", {"path": "/tmp/b.txt"}, {"path": "/home/user/b.txt"}),),
        }

        with patch(
            "myrm_agent_harness.agent.skill_agent.context.get_memory_manager",
            return_value=None,
        ):
            result1 = await hook.on_approval_correction("approval_correction", payload1)
            result2 = await hook.on_approval_correction("approval_correction", payload2)

        assert result1.output is not None and result1.output != ""
        assert result2.output is not None and result2.output != ""


class TestPersistence:
    """Tests for memory persistence via MemoryManager."""

    @pytest.mark.asyncio
    async def test_persists_when_manager_available(self, hook: CorrectionLearningHook) -> None:
        mock_manager = AsyncMock()
        mock_manager._store_semantic = AsyncMock()
        mock_manager._store_procedural = AsyncMock()

        payload = {
            "session_id": "s1",
            "corrections": (
                _edit("write_file", {"path": "/tmp/x"}, {"path": "/home/user/x"}),
                _edit("shell", {"command": "rm -rf build"}, {"command": "rm -r build"}),
            ),
        }

        with patch(
            "myrm_agent_harness.agent.skill_agent.context.get_memory_manager",
            return_value=mock_manager,
        ):
            result = await hook.on_approval_correction("approval_correction", payload)

        assert mock_manager._store_semantic.call_count == 1
        assert mock_manager._store_procedural.call_count == 1
        assert result.success is True

    @pytest.mark.asyncio
    async def test_graceful_when_no_manager(self, hook: CorrectionLearningHook) -> None:
        payload = {"session_id": "s1", "corrections": (_edit("write_file", {"path": "/a"}, {"path": "/b"}),)}

        with patch(
            "myrm_agent_harness.agent.skill_agent.context.get_memory_manager",
            return_value=None,
        ):
            result = await hook.on_approval_correction("approval_correction", payload)

        assert result.success is True
        assert result.output is not None

    @pytest.mark.asyncio
    async def test_persistence_failure_requeues(self, hook: CorrectionLearningHook) -> None:
        mock_manager = AsyncMock()
        mock_manager._store_semantic = AsyncMock(side_effect=RuntimeError("DB error"))
        mock_manager._store_procedural = AsyncMock()

        payload = {"session_id": "s1", "corrections": (_edit("write_file", {"path": "/a"}, {"path": "/b"}),)}

        with patch(
            "myrm_agent_harness.agent.skill_agent.context.get_memory_manager",
            return_value=mock_manager,
        ):
            result = await hook.on_approval_correction("approval_correction", payload)

        assert result.success is True
        assert len(hook._pending_preferences) == 1


class TestSummaryGeneration:
    """Tests for frontend-facing learning summaries."""

    def test_path_preference_summary(self, hook: CorrectionLearningHook) -> None:
        signal = CorrectionSignal(
            tool_name="write_file",
            arg_key="path",
            original_value="/tmp/x",
            corrected_value="/home/user/x",
            signal_class="path_preference",
        )
        summary = hook._build_summary(signal, "preference")
        assert "Remembered" in summary
        assert "/home/user/x" in summary
        assert "write_file" in summary

    def test_command_rule_summary(self, hook: CorrectionLearningHook) -> None:
        signal = CorrectionSignal(
            tool_name="shell",
            arg_key="command",
            original_value="bad",
            corrected_value="good",
            signal_class="command_rule",
        )
        summary = hook._build_summary(signal, "rule")
        assert "Learned rule" in summary
        assert "good" in summary


class TestEdgeCases:
    """Edge case tests."""

    @pytest.mark.asyncio
    async def test_empty_corrections(self, hook: CorrectionLearningHook) -> None:
        result = await hook.on_approval_correction("approval_correction", {"corrections": ()})
        assert result.success is True
        assert not result.output

    @pytest.mark.asyncio
    async def test_no_corrections_key(self, hook: CorrectionLearningHook) -> None:
        result = await hook.on_approval_correction("approval_correction", {})
        assert result.success is True

    @pytest.mark.asyncio
    async def test_corrections_not_iterable(self, hook: CorrectionLearningHook) -> None:
        result = await hook.on_approval_correction("approval_correction", {"corrections": 42})
        assert result.success is True

    def test_format_value_truncation(self) -> None:
        long_string = "x" * 200
        result = _format_value(long_string)
        assert len(result) == 123
        assert result.endswith("...")

    def test_format_value_none(self) -> None:
        assert _format_value(None) == "<none>"

    def test_format_value_normal(self) -> None:
        assert _format_value("/home/user/file.txt") == "/home/user/file.txt"

    def test_correction_signal_frozen(self) -> None:
        signal = CorrectionSignal(
            tool_name="test",
            arg_key="key",
            original_value="a",
            corrected_value="b",
            signal_class="arg_preference",
        )
        with pytest.raises(FrozenInstanceError):
            signal.tool_name = "other"  # type: ignore[misc]
