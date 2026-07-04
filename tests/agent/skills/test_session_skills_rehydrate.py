"""Tests for session skill rehydration from chat history."""

from __future__ import annotations

from langchain_core.messages import AIMessage, ToolMessage

from myrm_agent_harness.agent.skills.runtime.session_skills_rehydrate import (
    collect_loaded_skill_names_from_messages,
    merge_loaded_skill_name_sources,
    rehydrate_loaded_skills_from_history,
)
from myrm_agent_harness.backends.skills.types import SkillMetadata, SkillTrust


def _skill(name: str) -> SkillMetadata:
    return SkillMetadata(name=name, description="test", trust=SkillTrust.TRUSTED)


def test_collect_loaded_skill_names_from_successful_tool_call() -> None:
    messages = [
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "skill_select_tool",
                    "args": {"skill_names": ["alpha_skill", "beta_skill"], "reason": "need both"},
                    "id": "tc1",
                    "type": "tool_call",
                }
            ],
        ),
        ToolMessage(
            content=(
                "<skills_sop>\n"
                "alpha_skill：# alpha_skill\n\nSOP body\n"
                "beta_skill：# beta_skill\n\nAnother SOP\n"
                "</skills_sop>"
            ),
            tool_call_id="tc1",
            name="skill_select_tool",
        ),
    ]

    assert collect_loaded_skill_names_from_messages(messages) == ["alpha_skill", "beta_skill"]


def test_collect_loaded_skill_names_skips_failed_skill_entries() -> None:
    messages = [
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "skill_select_tool",
                    "args": {"skill_names": ["good_skill", "bad_skill"], "reason": "test"},
                    "id": "tc2",
                    "type": "tool_call",
                }
            ],
        ),
        ToolMessage(
            content=(
                "<skills_sop>\n"
                "good_skill：# good_skill\n\nOK\n"
                "bad_skill：# bad_skill\n\nError: failed to load skill document\n"
                "</skills_sop>"
            ),
            tool_call_id="tc2",
            name="skill_select_tool",
        ),
    ]

    assert collect_loaded_skill_names_from_messages(messages) == ["good_skill"]


def test_rehydrate_from_base_message_history() -> None:
    available = [_skill("alpha_skill"), _skill("beta_skill")]
    history = [
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "skill_select_tool",
                    "args": {"skill_names": ["alpha_skill"], "reason": "reuse"},
                    "id": "tc3",
                    "type": "tool_call",
                }
            ],
        ),
        ToolMessage(
            content="<skills_sop>\nalpha_skill：# alpha_skill\n\nLoaded\n</skills_sop>",
            tool_call_id="tc3",
            name="skill_select_tool",
        ),
    ]

    rehydrated = rehydrate_loaded_skills_from_history(history, available)
    assert [s.name for s in rehydrated] == ["alpha_skill"]


def test_rehydrate_from_agent_history_chat_req() -> None:
    available = [_skill("gamma_skill")]
    history = [
        [
            "assistant",
            (
                '{"__agent_history": true, "content": "done", '
                '"tool_calls": [{"name": "skill_select_tool", '
                '"args": {"skill_names": ["gamma_skill"], "reason": "prior turn"}}]}'
            ),
        ]
    ]

    rehydrated = rehydrate_loaded_skills_from_history(history, available)
    assert [s.name for s in rehydrated] == ["gamma_skill"]


def test_merge_loaded_skill_name_sources_unions_history_and_ssot() -> None:
    assert merge_loaded_skill_name_sources(
        ["alpha_skill", "beta_skill"],
        ["beta_skill", "gamma_skill"],
    ) == ["alpha_skill", "beta_skill", "gamma_skill"]


def test_rehydrate_from_ssot_only_when_history_empty() -> None:
    available = [_skill("delta_skill"), _skill("epsilon_skill")]
    rehydrated = rehydrate_loaded_skills_from_history(
        None,
        available,
        ["delta_skill", "epsilon_skill"],
    )
    assert [s.name for s in rehydrated] == ["delta_skill", "epsilon_skill"]


def test_rehydrate_ssot_fills_gap_after_compaction() -> None:
    """Simulates post-compaction: history lost skill_select, SSOT still has names."""
    available = [_skill("alpha_skill"), _skill("beta_skill")]
    history = [
        AIMessage(content="Summary of prior work without tool calls."),
    ]
    rehydrated = rehydrate_loaded_skills_from_history(
        history,
        available,
        ["alpha_skill", "beta_skill"],
    )
    assert [s.name for s in rehydrated] == ["alpha_skill", "beta_skill"]
