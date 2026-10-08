"""Tests for Hindsight Reflection LangChain Agent Tool and MemoryManager runtime integration.

[INPUT]
- toolkits.memory.strategies.hindsight::HindsightReflectionBuffer, HindsightRule, FailureTurn
- toolkits.memory.strategies.hindsight.tool::create_hindsight_reflection_tool, HindsightWarningInspectInput
- toolkits.memory.config::MemoryConfig
- toolkits.memory.manager::MemoryManager

[OUTPUT]
- Pytest test cases verifying Agent runtime consumption of Hindsight reflection warnings and scrubber.
"""

from __future__ import annotations

import json

import pytest
from langchain_core.tools import BaseTool

from myrm_agent_harness.toolkits.memory.config import MemoryConfig
from myrm_agent_harness.toolkits.memory.manager import MemoryManager
from myrm_agent_harness.toolkits.memory.strategies.hindsight import (
    FailureTurn,
    HindsightReflectionBuffer,
    HindsightRule,
    create_hindsight_reflection_tool,
)


@pytest.fixture
def populated_reflection_buffer() -> HindsightReflectionBuffer:
    buffer = HindsightReflectionBuffer()
    # Populate a real-world mistake pattern
    buffer.record_rule(
        HindsightRule(
            rule_id="rule-rm-protect",
            task_pattern="clean temp build artifacts",
            mistake_signature="rm -rf root directory without relative safety guard",
            correction_advice="Always verify directory path exists within workspace before deletion.",
            tags=["cleanup", "fs", "rm_rf"],
            confidence=0.95,
            hit_count=3,
        )
    )
    buffer.record_rule(
        HindsightRule(
            rule_id="rule-port-conflict",
            task_pattern="start dev server",
            mistake_signature="port 3000 already in use",
            correction_advice="Probe active ports using lsof/fuser or specify fallback port.",
            tags=["server", "network", "port"],
            confidence=0.85,
            hit_count=2,
        )
    )
    return buffer


def test_create_hindsight_reflection_tool_metadata(
    populated_reflection_buffer: HindsightReflectionBuffer,
) -> None:
    """Verify tool metadata conforms to LangChain BaseTool specifications."""
    tool = create_hindsight_reflection_tool(populated_reflection_buffer)

    assert isinstance(tool, BaseTool)
    assert tool.name == "inspect_hindsight_warnings"
    assert "pre-execution warnings" in tool.description.lower()
    assert tool.args_schema is not None
    fields = tool.args_schema.model_fields
    assert "task_goal" in fields
    assert "intended_tools" in fields
    assert "top_k" in fields


def test_agent_tool_invocation_matching_warning(
    populated_reflection_buffer: HindsightReflectionBuffer,
) -> None:
    """Verify Agent runtime invocation retrieves matching cautionary directives."""
    tool = create_hindsight_reflection_tool(populated_reflection_buffer)

    raw_result = tool.invoke(
        {
            "task_goal": "Please cleanup all build and fs artifacts in workspace",
            "intended_tools": ["run_command"],
            "top_k": 2,
        }
    )
    assert isinstance(raw_result, str)
    data = json.loads(raw_result)

    assert data["task_goal"] == "Please cleanup all build and fs artifacts in workspace"
    assert data["total_warnings"] >= 1
    warnings = data["warnings"]
    assert len(warnings) >= 1

    top_warning = warnings[0]
    assert top_warning["rule_id"] == "rule-rm-protect"
    assert "workspace" in top_warning["recommended_action"].lower()
    assert top_warning["confidence"] >= 0.9


def test_memory_manager_hindsight_reflection_lifecycle() -> None:
    """Verify MemoryManager facade provides reflection extraction and warning matching."""
    manager = MemoryManager(
        user_id="test_user",
        config=MemoryConfig(
            embedding_model="text-embedding-3-small",
            security_scan_enabled=False,
        ),
    )
    buffer = HindsightReflectionBuffer()

    # 1. Simulate task failure and trigger runtime reflection
    turns = [
        FailureTurn(
            turn_index=1,
            tool_name="run_command",
            tool_input={"CommandLine": "npm run start"},
            tool_output="Port 8080 is already allocated by another process",
            error_message="Port 8080 is already allocated",
        )
    ]

    rule = manager.reflect_on_failed_task(
        task_id="task-failure-101",
        task_goal="Launch production mock service",
        error_message="Port 8080 already in use",
        turns=turns,
        buffer=buffer,
    )

    assert rule is not None
    assert rule.rule_id.startswith("rule-")
    assert "port" in rule.correction_advice.lower() or "run_command" in rule.tags

    # 2. In a subsequent task, verify pre-execution warning is proactively retrieved
    warnings = manager.get_hindsight_pre_execution_warnings(
        task_goal="Launch production mock service",
        intended_tools=["run_command"],
        buffer=buffer,
        top_k=2,
    )

    assert len(warnings) >= 1
    matched = warnings[0]
    assert matched.rule_id == rule.rule_id
    assert matched.confidence >= 0.7
