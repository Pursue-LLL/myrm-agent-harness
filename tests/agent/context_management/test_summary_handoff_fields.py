"""Tests for blocked_items and next_steps handoff fields (Item 2).

Covers:
- StructuredSummary dataclass: default values, to_json serialization
- _FallbackSummaryModel: Pydantic model <-> StructuredSummary mapping
- summary_builder: create_summary_message rendering and U-curve ordering
- summary_prompts: template content verification
- summary_auditor: entity retention via to_json()
"""

from __future__ import annotations

import json

from langchain_core.messages import HumanMessage

from myrm_agent_harness.agent.context_management.infra.schemas import StructuredSummary
from myrm_agent_harness.agent.context_management.strategies.summary.summary_builder import (
    create_summary_message,
)


class TestStructuredSummaryHandoffFields:
    """StructuredSummary blocked_items / next_steps defaults and serialization."""

    def test_default_empty_lists(self) -> None:
        summary = StructuredSummary(user_goal="test")
        assert summary.blocked_items == []
        assert summary.next_steps == []

    def test_to_json_includes_blocked_items(self) -> None:
        summary = StructuredSummary(
            user_goal="test",
            blocked_items=["Missing dependency X"],
        )
        data = json.loads(summary.to_json())
        assert data["blocked_items"] == ["Missing dependency X"]

    def test_to_json_includes_next_steps(self) -> None:
        summary = StructuredSummary(
            user_goal="test",
            next_steps=["Run pytest on tests/test_api.py"],
        )
        data = json.loads(summary.to_json())
        assert data["next_steps"] == ["Run pytest on tests/test_api.py"]

    def test_to_json_omits_empty_blocked_items(self) -> None:
        summary = StructuredSummary(user_goal="test")
        data = json.loads(summary.to_json())
        assert "blocked_items" not in data

    def test_to_json_omits_empty_next_steps(self) -> None:
        summary = StructuredSummary(user_goal="test")
        data = json.loads(summary.to_json())
        assert "next_steps" not in data

    def test_to_json_both_fields(self) -> None:
        summary = StructuredSummary(
            user_goal="build API",
            blocked_items=["DB migration pending", "CI failing"],
            next_steps=["Fix migration", "Re-run CI", "Deploy"],
        )
        data = json.loads(summary.to_json())
        assert len(data["blocked_items"]) == 2
        assert len(data["next_steps"]) == 3

    def test_backward_compat_no_fields(self) -> None:
        """Old code creating StructuredSummary without new fields still works."""
        summary = StructuredSummary(
            user_goal="legacy",
            completed_actions=["done"],
            last_action="last",
        )
        assert summary.blocked_items == []
        assert summary.next_steps == []
        data = json.loads(summary.to_json())
        assert "blocked_items" not in data
        assert "next_steps" not in data


class TestFallbackSummaryModelMapping:
    """_FallbackSummaryModel -> StructuredSummary field mapping."""

    def test_fallback_model_maps_blocked_items(self) -> None:
        from myrm_agent_harness.agent.context_management.strategies.summary.summarizer import (
            _FallbackSummaryModel,
        )

        model = _FallbackSummaryModel(
            user_goal="test",
            blocked_items=["blocker A"],
            next_steps=["step 1"],
        )
        summary = model.to_structured_summary()
        assert summary.blocked_items == ["blocker A"]
        assert summary.next_steps == ["step 1"]

    def test_fallback_model_defaults(self) -> None:
        from myrm_agent_harness.agent.context_management.strategies.summary.summarizer import (
            _FallbackSummaryModel,
        )

        model = _FallbackSummaryModel(user_goal="test")
        summary = model.to_structured_summary()
        assert summary.blocked_items == []
        assert summary.next_steps == []


class TestSummaryBuilderHandoffFields:
    """create_summary_message rendering for blocked_items / next_steps."""

    def test_blocked_items_rendered(self) -> None:
        summary = StructuredSummary(
            user_goal="fix CI",
            blocked_items=["Test timeout on auth module"],
        )
        msg = create_summary_message(summary)
        assert "Blocked:" in msg.content
        assert "Test timeout on auth module" in msg.content

    def test_next_steps_rendered(self) -> None:
        summary = StructuredSummary(
            user_goal="deploy",
            next_steps=["Run integration tests", "Tag release v2.0"],
        )
        msg = create_summary_message(summary)
        assert "Next Steps:" in msg.content
        assert "Run integration tests" in msg.content
        assert "Tag release v2.0" in msg.content

    def test_blocked_items_none_filtered(self) -> None:
        summary = StructuredSummary(
            user_goal="test",
            blocked_items=["None"],
        )
        msg = create_summary_message(summary)
        assert "Blocked:" not in msg.content

    def test_next_steps_none_filtered(self) -> None:
        summary = StructuredSummary(
            user_goal="test",
            next_steps=["None"],
        )
        msg = create_summary_message(summary)
        assert "Next Steps:" not in msg.content

    def test_empty_blocked_no_section(self) -> None:
        summary = StructuredSummary(user_goal="test", blocked_items=[])
        msg = create_summary_message(summary)
        assert "Blocked:" not in msg.content

    def test_empty_next_steps_no_section(self) -> None:
        summary = StructuredSummary(user_goal="test", next_steps=[])
        msg = create_summary_message(summary)
        assert "Next Steps:" not in msg.content

    def test_blocked_items_limited_to_3(self) -> None:
        summary = StructuredSummary(
            user_goal="test",
            blocked_items=[f"blocker{i}" for i in range(6)],
        )
        msg = create_summary_message(summary)
        content = msg.content
        json_start = content.index("<!-- SUMMARY_JSON")
        text_part = content[:json_start]
        assert "blocker0" in text_part
        assert "blocker2" in text_part
        assert "blocker3" not in text_part

    def test_next_steps_limited_to_5(self) -> None:
        summary = StructuredSummary(
            user_goal="test",
            next_steps=[f"step{i}" for i in range(8)],
        )
        msg = create_summary_message(summary)
        content = msg.content
        json_start = content.index("<!-- SUMMARY_JSON")
        text_part = content[:json_start]
        assert "step0" in text_part
        assert "step4" in text_part
        assert "step5" not in text_part

    def test_u_curve_ordering_blocked_after_errors(self) -> None:
        """Blocked should appear after Errors & Fixes (both in tail zone)."""
        summary = StructuredSummary(
            user_goal="Goal",
            errors_and_fixes=["err -> fix"],
            blocked_items=["blocker X"],
            next_steps=["next action"],
            active_state="dev branch",
        )
        msg = create_summary_message(summary)
        content = msg.content
        error_pos = content.index("err -> fix")
        blocked_pos = content.index("blocker X")
        next_pos = content.index("next action")
        state_pos = content.index("dev branch")
        assert error_pos < blocked_pos < next_pos < state_pos

    def test_u_curve_ordering_next_steps_before_state(self) -> None:
        """Next Steps should appear before Working State (both in tail zone)."""
        summary = StructuredSummary(
            user_goal="Goal",
            next_steps=["step A"],
            active_state="main branch",
        )
        msg = create_summary_message(summary)
        content = msg.content
        step_pos = content.index("step A")
        state_pos = content.index("main branch")
        assert step_pos < state_pos

    def test_empty_string_items_filtered(self) -> None:
        """Empty strings in blocked_items/next_steps should be filtered out."""
        summary = StructuredSummary(
            user_goal="test",
            blocked_items=["real blocker", "", "  "],
            next_steps=["real step", ""],
        )
        msg = create_summary_message(summary)
        content = msg.content
        assert "real blocker" in content
        assert "real step" in content
        lines = content.split("\n")
        empty_items = [line for line in lines if line.strip() == "-"]
        assert len(empty_items) == 0, f"Found empty list items: {empty_items}"

    def test_full_u_curve_ordering_with_pending_asks(self) -> None:
        """Full ordering: errors -> blocked -> pending_user_asks -> next_steps -> state."""
        summary = StructuredSummary(
            user_goal="Goal",
            errors_and_fixes=["err1 -> fix1"],
            blocked_items=["blocker_alpha"],
            pending_user_asks=["pending_question"],
            next_steps=["next_action_beta"],
            active_state="feature-branch",
        )
        msg = create_summary_message(summary)
        content = msg.content
        err_pos = content.index("err1 -> fix1")
        blocked_pos = content.index("blocker_alpha")
        pending_pos = content.index("pending_question")
        next_pos = content.index("next_action_beta")
        state_pos = content.index("feature-branch")
        assert err_pos < blocked_pos < pending_pos < next_pos < state_pos

    def test_is_human_message(self) -> None:
        """Summary with new fields must still be HumanMessage (cache safety)."""
        summary = StructuredSummary(
            user_goal="test",
            blocked_items=["x"],
            next_steps=["y"],
        )
        msg = create_summary_message(summary)
        assert isinstance(msg, HumanMessage)

    def test_json_block_contains_new_fields(self) -> None:
        summary = StructuredSummary(
            user_goal="test",
            blocked_items=["critical blocker"],
            next_steps=["important step"],
        )
        msg = create_summary_message(summary)
        json_start = msg.content.index("<!-- SUMMARY_JSON") + len("<!-- SUMMARY_JSON")
        json_end = msg.content.index("-->", json_start)
        json_text = msg.content[json_start:json_end].strip()
        data = json.loads(json_text)
        assert data["blocked_items"] == ["critical blocker"]
        assert data["next_steps"] == ["important step"]


class TestSummaryPromptsHandoffFields:
    """Verify prompt templates include blocked_items / next_steps instructions."""

    def test_summary_prompt_has_blocked_items(self) -> None:
        from myrm_agent_harness.agent.context_management.strategies.summary.summary_prompts import (
            SUMMARY_PROMPT_TEMPLATE,
        )

        assert "blocked_items" in SUMMARY_PROMPT_TEMPLATE
        assert "max 3" in SUMMARY_PROMPT_TEMPLATE.lower()

    def test_summary_prompt_has_next_steps(self) -> None:
        from myrm_agent_harness.agent.context_management.strategies.summary.summary_prompts import (
            SUMMARY_PROMPT_TEMPLATE,
        )

        assert "next_steps" in SUMMARY_PROMPT_TEMPLATE
        assert "max 5" in SUMMARY_PROMPT_TEMPLATE.lower()

    def test_merge_prompt_has_blocked_items_rule(self) -> None:
        from myrm_agent_harness.agent.context_management.strategies.summary.summary_prompts import (
            SUMMARY_MERGE_PROMPT_TEMPLATE,
        )

        assert "blocked_items" in SUMMARY_MERGE_PROMPT_TEMPLATE
        assert "remove resolved blockers" in SUMMARY_MERGE_PROMPT_TEMPLATE.lower()

    def test_merge_prompt_has_next_steps_rule(self) -> None:
        from myrm_agent_harness.agent.context_management.strategies.summary.summary_prompts import (
            SUMMARY_MERGE_PROMPT_TEMPLATE,
        )

        assert "next_steps" in SUMMARY_MERGE_PROMPT_TEMPLATE
        assert "discard completed steps" in SUMMARY_MERGE_PROMPT_TEMPLATE.lower()


class TestSummaryAuditorEntityRetention:
    """Verify entity retention covers blocked_items / next_steps via to_json()."""

    def test_entity_in_blocked_items_retained(self) -> None:
        from myrm_agent_harness.agent.context_management.strategies.summary.summary_auditor import (
            audit_summary,
        )

        summary = StructuredSummary(
            user_goal="Refactor auth module",
            completed_actions=["updated code"],
            last_action="last",
            blocked_items=["app/auth/jwt.py import error"],
        )
        msgs = [HumanMessage(content="Working on app/auth/jwt.py refactoring " * 20)]
        entities = {"app/auth/jwt.py"}
        result = audit_summary(summary, msgs, entities=entities)
        assert result.entity_retained == 1

    def test_entity_in_next_steps_retained(self) -> None:
        from myrm_agent_harness.agent.context_management.strategies.summary.summary_auditor import (
            audit_summary,
        )

        summary = StructuredSummary(
            user_goal="Implement API",
            completed_actions=["built routes"],
            last_action="last",
            next_steps=["run pytest on tests/test_api.py"],
        )
        msgs = [HumanMessage(content="Working on tests/test_api.py testing " * 20)]
        entities = {"tests/test_api.py"}
        result = audit_summary(summary, msgs, entities=entities)
        assert result.entity_retained == 1


class TestRedactSummaryFieldsCoverage:
    """Verify _redact_summary_fields covers new list fields."""

    def test_redact_covers_blocked_items(self) -> None:
        from myrm_agent_harness.agent.context_management.strategies.summary.summarizer import (
            _redact_summary_fields,
        )

        summary = StructuredSummary(
            user_goal="test",
            blocked_items=["some text"],
        )
        result = _redact_summary_fields(summary)
        assert isinstance(result.blocked_items, list)
        assert len(result.blocked_items) == 1

    def test_redact_covers_next_steps(self) -> None:
        from myrm_agent_harness.agent.context_management.strategies.summary.summarizer import (
            _redact_summary_fields,
        )

        summary = StructuredSummary(
            user_goal="test",
            next_steps=["action item"],
        )
        result = _redact_summary_fields(summary)
        assert isinstance(result.next_steps, list)
        assert len(result.next_steps) == 1
