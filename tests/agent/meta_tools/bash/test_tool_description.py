"""Static bash TOOL_DESCRIPTION prompt hygiene tests."""

from __future__ import annotations

from myrm_agent_harness.agent.meta_tools.bash._tool_description import TOOL_DESCRIPTION


def test_ptc_section_uses_generic_agent_tool_name_not_web_search() -> None:
    assert "myrm_tools.<agent_tool_name>" in TOOL_DESCRIPTION
    assert "单次调用仍用 native tool" in TOOL_DESCRIPTION
    assert "myrm_tools.web_search_tool" not in TOOL_DESCRIPTION
    assert "myrm_tools.file_read_tool" not in TOOL_DESCRIPTION
    assert "myrm_tools.session_store(key" in TOOL_DESCRIPTION
