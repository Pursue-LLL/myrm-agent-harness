"""Tests for runtime intent-aware allowed-tools governance."""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from myrm_agent_harness.agent.middlewares.tooling._runtime_tool_governance import (
    compute_turn_allowed_names,
    derive_runtime_allowed_tools,
    extract_recent_human_text,
)


def test_extract_recent_human_text_uses_latest_human_message() -> None:
    messages: list[object] = [
        HumanMessage(content="first"),
        AIMessage(content="ack"),
        HumanMessage(content="latest user input"),
    ]

    assert extract_recent_human_text(messages) == "latest user input"


def test_extract_recent_human_text_handles_segment_list_content() -> None:
    messages: list[object] = [
        HumanMessage(
            content=[
                {"type": "text", "text": "segment A"},
                {"type": "text", "text": "segment B"},
            ]
        ),
    ]

    assert extract_recent_human_text(messages) == "segment A segment B"


def test_runtime_governance_disables_ui_tools_without_ui_intent() -> None:
    tool_names = ["render_ui_tool", "update_ui_data_tool", "web_search_tool"]
    allowed, reasons = derive_runtime_allowed_tools(
        tool_names=tool_names,
        recent_human_text="请解释一下这个问题的根因",
    )

    assert allowed == frozenset({"web_search_tool"})
    assert "ui_intent_gate" in reasons


def test_runtime_governance_keeps_ui_tools_for_ui_intent() -> None:
    tool_names = ["render_ui_tool", "update_ui_data_tool", "web_search_tool"]
    allowed, reasons = derive_runtime_allowed_tools(
        tool_names=tool_names,
        recent_human_text="请把结果做成可视化 dashboard 图表",
    )

    assert allowed is None
    assert reasons == ()


def test_runtime_governance_ui_keyword_does_not_match_build_substring() -> None:
    tool_names = ["render_ui_tool", "web_fetch_tool"]
    allowed, reasons = derive_runtime_allowed_tools(
        tool_names=tool_names,
        recent_human_text="please build and deploy this service",
    )

    assert allowed == frozenset({"web_fetch_tool"})
    assert "ui_intent_gate" in reasons


def test_runtime_governance_readonly_intent_filters_mutation_tools() -> None:
    tool_names = [
        "web_fetch_tool",
        "file_read_tool",
        "bash_code_execute_tool",
        "file_write_tool",
        "request_answer_user_tool",
    ]
    allowed, reasons = derive_runtime_allowed_tools(
        tool_names=tool_names,
        recent_human_text="请分析这段日志为什么会失败？",
    )

    assert allowed == frozenset({"web_fetch_tool", "file_read_tool", "request_answer_user_tool"})
    assert "readonly_intent_gate" in reasons


def test_runtime_governance_action_intent_keeps_mutation_tools() -> None:
    tool_names = ["file_write_tool", "web_fetch_tool"]
    allowed, reasons = derive_runtime_allowed_tools(
        tool_names=tool_names,
        recent_human_text="请修改这个配置文件并修复报错",
    )

    assert allowed is None
    assert reasons == ()


def test_compute_turn_allowed_names_merges_readonly_intent_gate() -> None:
    tool_names = ["file_read_tool", "file_write_tool", "web_search_tool"]
    messages: list[object] = [HumanMessage(content="请分析这段日志为什么会失败？")]

    allowed = compute_turn_allowed_names(
        tool_names=tool_names,
        messages=messages,
        loaded_skills=None,
    )

    assert allowed == frozenset({"file_read_tool", "web_search_tool"})


def test_compute_turn_allowed_names_returns_none_when_unrestricted() -> None:
    tool_names = ["file_read_tool", "web_search_tool"]
    messages: list[object] = [HumanMessage(content="请修改这个配置文件并修复报错")]

    allowed = compute_turn_allowed_names(
        tool_names=tool_names,
        messages=messages,
        loaded_skills=None,
    )

    assert allowed is None


def test_runtime_governance_readonly_intent_blocks_when_no_readonly_tools() -> None:
    tool_names = ["bash_code_execute_tool", "file_write_tool"]
    allowed, reasons = derive_runtime_allowed_tools(
        tool_names=tool_names,
        recent_human_text="请分析这段日志为什么会失败？",
    )

    assert allowed == frozenset()
    assert "readonly_intent_gate" in reasons


def test_compute_turn_allowed_names_returns_empty_frozenset_for_block_all() -> None:
    tool_names = ["bash_code_execute_tool"]
    messages: list[object] = [HumanMessage(content="请分析这段日志为什么会失败？")]

    allowed = compute_turn_allowed_names(
        tool_names=tool_names,
        messages=messages,
        loaded_skills=None,
    )

    assert allowed == frozenset()


def test_derive_runtime_allowed_tools_empty_tool_names() -> None:
    allowed, reasons = derive_runtime_allowed_tools(
        tool_names=[],
        recent_human_text="analyze this",
    )

    assert allowed is None
    assert reasons == ()


def test_compute_turn_allowed_names_empty_tool_names() -> None:
    assert compute_turn_allowed_names([], [], None) is None


def test_extract_recent_human_text_skips_non_human_messages() -> None:
    messages: list[object] = [AIMessage(content="assistant only")]
    assert extract_recent_human_text(messages) is None


def test_compute_turn_allowed_names_applies_skill_attenuation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    tool_names = ["file_read_tool", "bash_code_execute_tool"]
    messages: list[object] = [HumanMessage(content="请修改这个配置文件并修复报错")]
    loaded_skills = [SimpleNamespace(name="demo-skill")]

    monkeypatch.setattr(
        "myrm_agent_harness.agent.skills.runtime.attenuator.attenuate_tools",
        lambda names, _skills: SimpleNamespace(
            tool_names=["file_read_tool"],
            removed_tools=["bash_code_execute_tool"],
        ),
    )

    allowed = compute_turn_allowed_names(
        tool_names=tool_names,
        messages=messages,
        loaded_skills=loaded_skills,
    )

    assert allowed == frozenset({"file_read_tool"})
