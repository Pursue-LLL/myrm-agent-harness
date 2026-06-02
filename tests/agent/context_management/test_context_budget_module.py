"""Tests for context_budget module (ContextBudget, calculate_context_budget, format_budget_log)."""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from myrm_agent_harness.agent.context_management.infra.context_budget import (
    ContextBudget,
    ContextHealthStatus,
    calculate_context_budget,
    format_budget_log,
)
from myrm_agent_harness.agent.context_management.infra.schemas import ContextConfig

CT = 50_000  # compress_threshold for max_context_tokens=100_000
ST = 90_000  # summarize_trigger_threshold for max_context_tokens=100_000


@pytest.fixture
def config() -> ContextConfig:
    return ContextConfig(max_context_tokens=100_000, compress_min_save=3000)


def _budget(current: int, config: ContextConfig) -> ContextBudget:
    return ContextBudget(current_tokens=current, compress_threshold=CT, summarize_threshold=ST, config=config)


class TestContextHealthStatus:
    def test_enum_values(self) -> None:
        assert ContextHealthStatus.HEALTHY == "healthy"
        assert ContextHealthStatus.WARNING == "warning"
        assert ContextHealthStatus.CRITICAL == "critical"


class TestContextBudget:
    def test_healthy_status(self, config: ContextConfig) -> None:
        b = _budget(10_000, config)
        assert b.health_status == ContextHealthStatus.HEALTHY
        assert b.compress_usage == pytest.approx(0.2)
        assert b.summarize_usage == pytest.approx(10_000 / ST)

    def test_warning_status(self, config: ContextConfig) -> None:
        b = _budget(45_000, config)
        assert b.health_status == ContextHealthStatus.WARNING
        assert b.compress_usage == pytest.approx(0.9)

    def test_critical_status(self, config: ContextConfig) -> None:
        assert _budget(80_000, config).health_status == ContextHealthStatus.CRITICAL

    def test_remaining_until_compress(self, config: ContextConfig) -> None:
        assert _budget(30_000, config).remaining_until_compress == 20_000

    def test_remaining_until_compress_overflow(self, config: ContextConfig) -> None:
        assert _budget(60_000, config).remaining_until_compress == 0

    def test_remaining_until_summarize(self, config: ContextConfig) -> None:
        assert _budget(70_000, config).remaining_until_summarize == 20_000

    def test_remaining_ratio(self, config: ContextConfig) -> None:
        assert _budget(45_000, config).remaining_ratio == pytest.approx(1.0 - 45_000 / ST)

    def test_remaining_ratio_overflow(self, config: ContextConfig) -> None:
        assert _budget(100_000, config).remaining_ratio == 0.0

    def test_zero_thresholds(self, config: ContextConfig) -> None:
        b = ContextBudget(current_tokens=100, compress_threshold=0, summarize_threshold=0, config=config)
        assert b.compress_usage == 0.0
        assert b.summarize_usage == 0.0
        assert b.remaining_ratio == 1.0

    def test_dynamic_compress_min_save_plenty_of_space(self, config: ContextConfig) -> None:
        assert _budget(10_000, config).get_dynamic_compress_min_save() == 3000

    def test_dynamic_compress_min_save_moderate(self, config: ContextConfig) -> None:
        assert _budget(63_000, config).get_dynamic_compress_min_save() == int(3000 * 0.6)

    def test_dynamic_compress_min_save_tight(self, config: ContextConfig) -> None:
        assert _budget(79_000, config).get_dynamic_compress_min_save() == int(3000 * 0.4)

    def test_dynamic_compress_min_save_emergency(self, config: ContextConfig) -> None:
        assert _budget(86_000, config).get_dynamic_compress_min_save() == max(500, int(3000 * 0.2))

    def test_calculate_dynamic_thresholds_early(self, config: ContextConfig) -> None:
        threshold, min_save = _budget(5_000, config).calculate_dynamic_thresholds(turn_count=3)
        assert threshold == CT
        assert min_save == 3000

    def test_calculate_dynamic_thresholds_relaxed(self, config: ContextConfig) -> None:
        threshold, _ = _budget(20_000, config).calculate_dynamic_thresholds(turn_count=10, estimated_remaining_turns=10)
        assert threshold == CT

    def test_calculate_dynamic_thresholds_moderate_urgency(self, config: ContextConfig) -> None:
        threshold, _ = _budget(50_000, config).calculate_dynamic_thresholds(turn_count=10, estimated_remaining_turns=10)
        assert threshold < CT

    def test_calculate_dynamic_thresholds_high_urgency(self, config: ContextConfig) -> None:
        threshold, _ = _budget(80_000, config).calculate_dynamic_thresholds(turn_count=10, estimated_remaining_turns=10)
        assert threshold < CT

    def test_calculate_dynamic_thresholds_very_high_urgency(self, config: ContextConfig) -> None:
        threshold, _ = _budget(85_000, config).calculate_dynamic_thresholds(turn_count=10, estimated_remaining_turns=20)
        assert threshold == int(CT * 0.50)

    def test_to_dict(self, config: ContextConfig) -> None:
        d = _budget(30_000, config).to_dict()
        assert d["current_tokens"] == 30_000
        assert d["compress_threshold"] == CT
        assert d["summarize_threshold"] == ST
        assert "compress_usage_percent" in d
        assert "health_status" in d
        assert "dynamic_compress_min_save" in d

    def test_to_progress_bar(self, config: ContextConfig) -> None:
        bar = _budget(45_000, config).to_progress_bar()
        assert "█" in bar and "░" in bar and "tokens" in bar

    def test_to_progress_bar_emoji(self, config: ContextConfig) -> None:
        assert "" in _budget(10_000, config).to_progress_bar()
        assert "" in _budget(42_000, config).to_progress_bar()
        assert "" in _budget(80_000, config).to_progress_bar()

    def test_to_detailed_view(self, config: ContextConfig) -> None:
        view = _budget(45_000, config).to_detailed_view()
        assert "CONTEXT BUDGET" in view
        assert "Compress" in view
        assert "Summarize" in view


class TestCalculateContextBudget:
    def test_with_messages(self) -> None:
        messages = [HumanMessage(content="Hello"), AIMessage(content="Hi there")]
        budget = calculate_context_budget(messages)
        assert budget.current_tokens > 0
        assert budget.compress_threshold > 0

    def test_with_custom_config(self, config: ContextConfig) -> None:
        budget = calculate_context_budget([HumanMessage(content="Hello")], config=config)
        assert budget.compress_threshold == CT
        assert budget.summarize_threshold == int(100_000 * 0.8)

    def test_with_default_config(self) -> None:
        budget = calculate_context_budget([HumanMessage(content="Test")])
        assert budget.config is not None


class TestFormatBudgetLog:
    def test_healthy_format(self, config: ContextConfig) -> None:
        log = format_budget_log(_budget(10_000, config))
        assert "" in log and "Context Budget" in log

    def test_warning_format(self, config: ContextConfig) -> None:
        assert "" in format_budget_log(_budget(42_000, config))

    def test_critical_format(self, config: ContextConfig) -> None:
        assert "" in format_budget_log(_budget(80_000, config))
