"""Tests for dropped_manifest module."""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from myrm_agent_harness.agent.context_management.infra.schemas import StructuredSummary
from myrm_agent_harness.agent.context_management.strategies.summary.dropped_manifest import (
    build_dropped_manifest,
    contains_constraint_marker,
)


class TestContainsConstraintMarker:
    def test_english_constraint_keywords(self) -> None:
        assert contains_constraint_marker("Please remember to keep the UI consistent")
        assert contains_constraint_marker("Do not touch the config file")
        assert contains_constraint_marker("must not delete test fixtures")
        assert contains_constraint_marker("This is important: keep the API stable")

    def test_chinese_constraint_keywords(self) -> None:
        assert contains_constraint_marker("请务必不要修改 main.py")
        assert contains_constraint_marker("必须保持接口兼容")
        assert contains_constraint_marker("记住：不要用 emoji")

    def test_plain_content_is_not_constraint(self) -> None:
        assert not contains_constraint_marker("今天天气不错")
        assert not contains_constraint_marker("Hello, how are you?")
        assert not contains_constraint_marker("The build passed.")

    def test_case_insensitive(self) -> None:
        assert contains_constraint_marker("NEVER touch production")
        assert contains_constraint_marker("Please REMEMBER the deadline")


class TestBuildDroppedManifest:
    def test_returns_empty_when_nothing_dropped(self) -> None:
        msgs = [
            SystemMessage(content="system"),
            HumanMessage(content="Hello"),
        ]
        result = build_dropped_manifest(
            msgs,
            protected_ids={id(msgs[0]), id(msgs[1])},
            recent_ids=set(),
        )
        assert result == []

    def test_captures_dropped_user_constraint(self) -> None:
        keep_msg = HumanMessage(content="Current question")
        dropped_msg = HumanMessage(content="Remember: do not modify the config file")
        msgs = [keep_msg, dropped_msg]
        result = build_dropped_manifest(
            msgs,
            protected_ids={id(keep_msg)},
            recent_ids=set(),
        )
        assert len(result) == 1
        assert "config file" in result[0]

    def test_ignores_dropped_plain_user_message(self) -> None:
        keep_msg = HumanMessage(content="Current question")
        dropped_msg = HumanMessage(content="Can you also check the weather?")
        msgs = [keep_msg, dropped_msg]
        result = build_dropped_manifest(
            msgs,
            protected_ids={id(keep_msg)},
            recent_ids=set(),
        )
        assert result == []

    def test_limits_manifest_size(self) -> None:
        keep_msg = HumanMessage(content="Current question")
        dropped_msgs = [
            HumanMessage(content=f"Remember: keep constraint {i} in mind")
            for i in range(10)
        ]
        msgs = [keep_msg, *dropped_msgs]
        result = build_dropped_manifest(
            msgs,
            protected_ids={id(keep_msg)},
            recent_ids=set(),
        )
        assert len(result) <= 3

    def test_deduplicates_identical_snippets(self) -> None:
        keep_msg = HumanMessage(content="Current question")
        dropped_msgs = [
            HumanMessage(content="Remember: keep it simple"),
            HumanMessage(content="Remember: keep it simple"),
        ]
        msgs = [keep_msg, *dropped_msgs]
        result = build_dropped_manifest(
            msgs,
            protected_ids={id(keep_msg)},
            recent_ids=set(),
        )
        assert len(result) == 1

    def test_redacts_credentials(self) -> None:
        keep_msg = HumanMessage(content="Current question")
        # sk- + 48+ [a-zA-Z0-9_-] matches the OpenAI API-key pattern.
        api_key = "sk-" + "a" * 48
        dropped_msg = HumanMessage(
            content=f"Remember: the API key is {api_key}, do not commit it"
        )
        msgs = [keep_msg, dropped_msg]
        result = build_dropped_manifest(
            msgs,
            protected_ids={id(keep_msg)},
            recent_ids=set(),
        )
        assert len(result) == 1
        assert api_key not in result[0]

    def test_ignores_ai_and_tool_messages(self) -> None:
        keep_msg = HumanMessage(content="Current question")
        dropped_ai = AIMessage(content="Remember: I will fix it tomorrow")
        dropped_tool = ToolMessage(content="Remember: result was ok", name="t", tool_call_id="c")
        msgs = [keep_msg, dropped_ai, dropped_tool]
        result = build_dropped_manifest(
            msgs,
            protected_ids={id(keep_msg)},
            recent_ids=set(),
        )
        assert result == []

    def test_ignores_dropped_system_messages(self) -> None:
        keep_msg = HumanMessage(content="Current question")
        # Harness-injected system prompts (memory context templates, agent
        # instructions) must never surface as "dropped user constraints" —
        # that would leak pipeline internals into the GUI.
        dropped_system = SystemMessage(
            content="Remember: you MUST append a <cite:MEMORY_ID> citation tag"
        )
        msgs = [keep_msg, dropped_system]
        result = build_dropped_manifest(
            msgs,
            protected_ids={id(keep_msg)},
            recent_ids=set(),
        )
        assert result == []

    def test_truncates_long_snippets(self) -> None:
        keep_msg = HumanMessage(content="Current question")
        long_content = "Remember: " + "x" * 500
        dropped_msg = HumanMessage(content=long_content)
        msgs = [keep_msg, dropped_msg]
        result = build_dropped_manifest(
            msgs,
            protected_ids={id(keep_msg)},
            recent_ids=set(),
        )
        assert len(result) == 1
        assert len(result[0]) <= 160


class TestDroppedManifestPromptIsolation:
    def test_manifest_is_excluded_from_to_json(self) -> None:
        """dropped_manifest is audit metadata — it must never leak into to_json().

        to_json() feeds create_summary_message() and incremental-merge prompts,
        so including it would inflate prompt-cache payloads and leak pipeline
        internals into the model.
        """
        summary = StructuredSummary(
            user_goal="goal",
            dropped_manifest=["Remember: keep the API stable"],
        )
        serialized = summary.to_json()
        assert "dropped_manifest" not in serialized
        assert "keep the API stable" not in serialized

    def test_manifest_defaults_to_empty_list(self) -> None:
        summary = StructuredSummary(user_goal="goal")
        assert summary.dropped_manifest == []
