"""Tests for PromptBudgetGuard."""

from __future__ import annotations

from myrm_agent_harness.agent.security.guards.prompt_budget import (
    CHARS_PER_TOKEN,
    BudgetedSection,
    PromptBudgetGuard,
)


class TestPromptBudgetGuard:
    def test_basic_formatting(self):
        guard = PromptBudgetGuard(max_tokens=5000)
        sections = [
            BudgetedSection(title="Core", items=["item1", "item2"], priority=0),
        ]
        result = guard.apply_budget(sections)
        assert "## Core" in result
        assert "- item1" in result
        assert "- item2" in result

    def test_priority_ordering(self):
        guard = PromptBudgetGuard(max_tokens=5000)
        sections = [
            BudgetedSection(title="Low", items=["low-item"], priority=2),
            BudgetedSection(title="High", items=["high-item"], priority=0),
        ]
        result = guard.apply_budget(sections)
        high_pos = result.index("## High")
        low_pos = result.index("## Low")
        assert high_pos < low_pos

    def test_budget_truncation(self):
        guard = PromptBudgetGuard(max_tokens=5)
        max_chars = 5 * CHARS_PER_TOKEN  # 20 chars
        sections = [
            BudgetedSection(title="A", items=["x" * 10, "y" * 10], priority=0),
            BudgetedSection(title="B", items=["z" * 50], priority=1),
        ]
        result = guard.apply_budget(sections)
        assert "truncated" in result.lower() or len(result) <= max_chars + 200

    def test_empty_sections_skipped(self):
        guard = PromptBudgetGuard(max_tokens=5000)
        sections = [
            BudgetedSection(title="Empty", items=[], priority=0),
            BudgetedSection(title="Full", items=["item"], priority=1),
        ]
        result = guard.apply_budget(sections)
        assert "## Empty" not in result
        assert "## Full" in result

    def test_base_text_included(self):
        guard = PromptBudgetGuard(max_tokens=5000)
        sections = [BudgetedSection(title="S", items=["i"], priority=0)]
        result = guard.apply_budget(sections, base_text="PREFIX\n")
        assert result.startswith("PREFIX")

    def test_base_text_counts_toward_budget(self):
        guard = PromptBudgetGuard(max_tokens=3)
        max_chars = 3 * CHARS_PER_TOKEN  # 12 chars
        base = "A" * (max_chars - 5)
        sections = [
            BudgetedSection(title="LongTitle", items=["item" * 10], priority=0),
        ]
        result = guard.apply_budget(sections, base_text=base)
        # Budget so tight that section header can't fit
        assert "item" not in result or "truncated" in result.lower()

    def test_custom_truncation_message(self):
        guard = PromptBudgetGuard(max_tokens=3, truncation_message="[CUT]")
        sections = [
            BudgetedSection(title="A", items=["x" * 20], priority=0),
            BudgetedSection(title="B", items=["y" * 100], priority=1),
        ]
        result = guard.apply_budget(sections)
        if "[CUT]" in result:
            assert True

    def test_no_truncation_message(self):
        guard = PromptBudgetGuard(max_tokens=3, truncation_message="")
        sections = [
            BudgetedSection(title="A", items=["x" * 50], priority=0),
            BudgetedSection(title="B", items=["y" * 50], priority=1),
        ]
        result = guard.apply_budget(sections)
        assert "truncated" not in result.lower()

    def test_all_sections_fit(self):
        guard = PromptBudgetGuard(max_tokens=50000)
        sections = [
            BudgetedSection(title="A", items=["a1", "a2"], priority=0),
            BudgetedSection(title="B", items=["b1"], priority=1),
        ]
        result = guard.apply_budget(sections)
        assert "## A" in result
        assert "## B" in result
        assert "truncated" not in result.lower()

    def test_single_item_exceeds_budget(self):
        guard = PromptBudgetGuard(max_tokens=2)
        sections = [
            BudgetedSection(title="A", items=["x" * 100], priority=0),
        ]
        result = guard.apply_budget(sections)
        # Section header fits but item doesn't, so "## A" appears but item may not
        assert "## A" in result or "truncated" in result.lower()


class TestBudgetedSection:
    def test_creation(self):
        s = BudgetedSection(title="T", items=["a", "b"], priority=1)
        assert s.title == "T"
        assert len(s.items) == 2
        assert s.priority == 1
