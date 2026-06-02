"""Tests for delegate_task tool registrations in security subsystem.

Validates:
1. TOOL_SAFETY_METADATA has delegate_task (not old spawn_subagent_tool)
2. TOOL_PERMISSION_MAP has delegate_task
3. TOOL_SEMANTIC_MAP has delegate_task in EXECUTE group
4. Loop suggestions have delegate_task registered
5. Loop suggestions core static map has delegate_task
"""

from myrm_agent_harness.agent.security.guards.loop_guard_types import TOOL_SEMANTIC_MAP, ToolGroup
from myrm_agent_harness.agent.security.guards.loop_suggestions import _DYNAMIC_GENERATORS
from myrm_agent_harness.agent.security.guards.loop_suggestions.core import TOOL_SUGGESTIONS
from myrm_agent_harness.agent.security.tool_registry import TOOL_PERMISSION_MAP, TOOL_SAFETY_METADATA


class TestToolSafetyMetadata:
    def test_delegate_task_registered(self):
        assert "delegate_task_tool" in TOOL_SAFETY_METADATA

    def test_delegate_task_is_concurrent_safe(self):
        meta = TOOL_SAFETY_METADATA["delegate_task_tool"]
        assert meta.is_concurrent_safe is True
        assert meta.is_read_only is False
        assert meta.is_destructive is False

    def test_batch_delegate_registered(self):
        assert "batch_delegate_tasks_tool" in TOOL_SAFETY_METADATA

    def test_old_names_removed(self):
        assert "spawn_subagent_tool" not in TOOL_SAFETY_METADATA


class TestToolPermissionMap:
    def test_delegate_task_mapped(self):
        assert "delegate_task_tool" in TOOL_PERMISSION_MAP
        assert TOOL_PERMISSION_MAP["delegate_task_tool"] == "delegate_agent"

    def test_batch_delegate_mapped(self):
        assert "batch_delegate_tasks_tool" in TOOL_PERMISSION_MAP
        assert TOOL_PERMISSION_MAP["batch_delegate_tasks_tool"] == "delegate_agent"

    def test_old_names_removed(self):
        assert "spawn_subagent_tool" not in TOOL_PERMISSION_MAP


class TestToolSemanticMap:
    def test_delegate_task_in_execute_group(self):
        assert "delegate_task_tool" in TOOL_SEMANTIC_MAP
        assert TOOL_SEMANTIC_MAP["delegate_task_tool"] == ToolGroup.EXECUTE

    def test_old_name_removed(self):
        assert "spawn_subagent_tool" not in TOOL_SEMANTIC_MAP


class TestLoopSuggestions:
    def test_dynamic_generator_registered(self):
        assert "delegate_task_tool" in _DYNAMIC_GENERATORS

    def test_old_name_removed_from_dynamic(self):
        assert "spawn_subagent_tool" not in _DYNAMIC_GENERATORS

    def test_static_suggestion_exists(self):
        assert "delegate_task_tool" in TOOL_SUGGESTIONS

    def test_old_name_removed_from_static(self):
        assert "spawn_subagent_tool" not in TOOL_SUGGESTIONS
