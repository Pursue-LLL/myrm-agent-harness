"""Prompt-contract tests for generated MCP function documentation."""

from __future__ import annotations

from myrm_agent_harness.agent.skills.mcp.core_generator import SKILL_USAGE_TEMPLATE
from myrm_agent_harness.agent.skills.mcp.schema_doc_utils import TOOL_DOC_TEMPLATE


def test_function_example_awaits_async_mcp_proxy() -> None:
    rendered = TOOL_DOC_TEMPLATE.format(
        tool_name="search",
        skill_name="demo_skill",
        tool_desc="Search records.",
        params_section="## Parameters\n\nNo parameters required.",
        call_example="",
    )

    assert "result = await search()" in rendered
    assert "result = search()" not in rendered


def test_mcp_prompts_distinguish_parsed_values_from_known_fields() -> None:
    assert "only access fields explicitly documented" in SKILL_USAGE_TEMPLATE
    assert "Only access fields explicitly documented" in TOOL_DOC_TEMPLATE
    assert "do NOT `json.loads()`" in SKILL_USAGE_TEMPLATE


def test_mcp_usage_prompt_omits_runtime_noise() -> None:
    assert "sandbox blocks it" not in SKILL_USAGE_TEMPLATE
    assert "~500ms" not in SKILL_USAGE_TEMPLATE
    assert "thousands of tokens" not in SKILL_USAGE_TEMPLATE
    assert "built-in PTC" not in SKILL_USAGE_TEMPLATE
    assert "func_a" not in SKILL_USAGE_TEMPLATE
    assert "item['name']" not in SKILL_USAGE_TEMPLATE


def test_mcp_skill_usage_template_owns_workflow_sop() -> None:
    """MCP-specific workflow must live in Skill usage template, not bash tool."""
    assert "/mcp/{skill_name}/<function_name>.md" in SKILL_USAGE_TEMPLATE
    assert "file_read_tool" in SKILL_USAGE_TEMPLATE
    assert "bash_code_execute_tool" in SKILL_USAGE_TEMPLATE
    assert "Scenario B" in SKILL_USAGE_TEMPLATE
    assert "timeout=120" in SKILL_USAGE_TEMPLATE
    assert "OBSERVATION" in SKILL_USAGE_TEMPLATE
