"""[INPUT] Harness budget_scaling submodule exports and subagent configuration loader.
[OUTPUT] Unit tests verifying zero-disruption configuration migration and 80% watermark alerts.
[POS] Unit tests for Subagent Concurrency & Tool Budget Adaptive Scaling (Item 31).
"""

from __future__ import annotations

from myrm_agent_harness.agent.sub_agents.budget_scaling import (
    DEFAULT_MAX_CHILDREN_PER_AGENT,
    DEFAULT_MAX_DESCENDANTS_PER_RUN,
    DEFAULT_SCALED_CONCURRENCY,
    DEFAULT_SCALED_MAX_TURNS,
    DEFAULT_WATERMARK_THRESHOLD_RATIO,
    ConfigUpgradeMigrator,
    SubagentWatermarkGuard,
)


def test_migrator_lifts_legacy_default_concurrency_and_turns() -> None:
    # 1. Standard legacy defaults (concurrency=3, max_turns=50)
    raw = {"concurrency_limit": 3, "max_turns": 50}
    migrated_dict, result = ConfigUpgradeMigrator.migrate_config_dict(raw)

    assert result.migrated is True
    assert result.concurrency_migrated is True
    assert result.max_turns_migrated is True
    assert result.old_concurrency == 3
    assert result.new_concurrency == DEFAULT_SCALED_CONCURRENCY  # 10
    assert result.old_max_turns == 50
    assert result.new_max_turns == DEFAULT_SCALED_MAX_TURNS  # 250
    assert migrated_dict["concurrency_limit"] == 10
    assert migrated_dict["max_turns"] == 250
    assert migrated_dict["max_children_per_agent"] == DEFAULT_MAX_CHILDREN_PER_AGENT
    assert migrated_dict["max_descendants_per_run"] == DEFAULT_MAX_DESCENDANTS_PER_RUN

    # 2. Alternative legacy defaults (concurrency=5, max_turns=25)
    raw_alt = {"concurrency_limit": 5, "max_turns": 25}
    _, result_alt = ConfigUpgradeMigrator.migrate_config_dict(raw_alt)
    assert result_alt.migrated is True
    assert result_alt.concurrency_migrated is True
    assert result_alt.max_turns_migrated is True
    assert result_alt.new_concurrency == 10
    assert result_alt.new_max_turns == 250


def test_migrator_preserves_user_customized_config() -> None:
    # 1. Custom non-default values (concurrency=8, max_turns=120)
    raw_custom = {
        "concurrency_limit": 8,
        "max_turns": 120,
        "max_children_per_agent": 6,
        "max_descendants_per_run": 30,
    }
    migrated_dict, result = ConfigUpgradeMigrator.migrate_config_dict(raw_custom)

    assert result.migrated is False
    assert result.concurrency_migrated is False
    assert result.max_turns_migrated is False
    assert result.old_concurrency == 8
    assert result.new_concurrency == 8
    assert result.old_max_turns == 120
    assert result.new_max_turns == 120
    assert migrated_dict["concurrency_limit"] == 8
    assert migrated_dict["max_turns"] == 120
    assert migrated_dict["max_children_per_agent"] == 6
    assert migrated_dict["max_descendants_per_run"] == 30

    # 2. Hybrid: legacy concurrency (3) but customized max_turns (88)
    raw_hybrid = {"concurrency_limit": 3, "max_turns": 88}
    migrated_hybrid, result_hybrid = ConfigUpgradeMigrator.migrate_config_dict(raw_hybrid)
    assert result_hybrid.migrated is True
    assert result_hybrid.concurrency_migrated is True
    assert result_hybrid.max_turns_migrated is False
    assert result_hybrid.new_concurrency == 10
    assert result_hybrid.new_max_turns == 88
    assert migrated_hybrid["concurrency_limit"] == 10
    assert migrated_hybrid["max_turns"] == 88


def test_migrator_handles_missing_and_malformed_values() -> None:
    # Empty dict -> assigned scaled defaults
    migrated_dict, result = ConfigUpgradeMigrator.migrate_config_dict({})
    assert result.migrated is False
    assert migrated_dict["concurrency_limit"] == DEFAULT_SCALED_CONCURRENCY
    assert migrated_dict["max_turns"] == DEFAULT_SCALED_MAX_TURNS

    # Malformed non-numeric values -> gracefully fallback to defaults
    malformed = {"concurrency_limit": "not-an-int", "max_turns": None}
    migrated_malformed, _ = ConfigUpgradeMigrator.migrate_config_dict(malformed)
    assert migrated_malformed["concurrency_limit"] == DEFAULT_SCALED_CONCURRENCY
    assert migrated_malformed["max_turns"] == DEFAULT_SCALED_MAX_TURNS


def test_watermark_guard_below_threshold_does_not_alert() -> None:
    guard = SubagentWatermarkGuard(DEFAULT_WATERMARK_THRESHOLD_RATIO)  # 0.80

    # 100 / 250 = 40%
    alert1 = guard.record_turn_and_check("subagent-alpha", current_turn=100, max_turns=250)
    assert alert1 is None
    assert guard.is_task_alerted("subagent-alpha") is False
    assert guard.get_current_turn("subagent-alpha") == 100

    # 199 / 250 = 79.6% (strictly below 80%)
    alert2 = guard.record_turn_and_check("subagent-alpha", current_turn=199, max_turns=250)
    assert alert2 is None
    assert guard.is_task_alerted("subagent-alpha") is False


def test_watermark_guard_fires_once_at_80_percent_and_debounces() -> None:
    guard = SubagentWatermarkGuard(0.80)

    # 200 / 250 = 80.0% -> First trigger
    alert = guard.record_turn_and_check("subagent-beta", current_turn=200, max_turns=250)
    assert alert is not None
    assert alert.task_id == "subagent-beta"
    assert alert.current_turn == 200
    assert alert.max_turns == 250
    assert alert.usage_ratio == 0.80
    assert alert.turns_remaining == 50
    assert "reached 80.0% of turn budget" in alert.warning_message
    assert guard.is_task_alerted("subagent-beta") is True

    # Subsequent turns: 201, 202 -> Debounced, return None
    alert_next = guard.record_turn_and_check("subagent-beta", current_turn=201, max_turns=250)
    assert alert_next is None

    alert_further = guard.record_turn_and_check("subagent-beta", current_turn=249, max_turns=250)
    assert alert_further is None


def test_watermark_guard_clear_and_reset() -> None:
    guard = SubagentWatermarkGuard(0.80)
    guard.record_turn_and_check("subagent-gamma", current_turn=200, max_turns=250)
    assert guard.is_task_alerted("subagent-gamma") is True

    # Clear individual task
    guard.clear_task("subagent-gamma")
    assert guard.is_task_alerted("subagent-gamma") is False
    assert guard.get_current_turn("subagent-gamma") == 0

    # Can fire again after clear
    alert = guard.record_turn_and_check("subagent-gamma", current_turn=210, max_turns=250)
    assert alert is not None
    assert alert.current_turn == 210

    # Reset all
    guard.reset_all()
    assert guard.is_task_alerted("subagent-gamma") is False
