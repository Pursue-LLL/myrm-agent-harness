"""Tests for Combo routing data models."""

from __future__ import annotations

import pytest

from myrm_agent_harness.toolkits.llms.routing.combo.combo_types import (
    ComboConfig,
    ComboTarget,
    RoutingStrategy,
)


class TestRoutingStrategy:
    def test_all_values_are_strings(self) -> None:
        for s in RoutingStrategy:
            assert isinstance(s.value, str)

    def test_seven_strategies_exist(self) -> None:
        assert len(RoutingStrategy) == 7


class TestComboTarget:
    def test_minimal_construction(self) -> None:
        t = ComboTarget(provider_id="openai", model="gpt-4o")
        assert t.provider_id == "openai"
        assert t.model == "gpt-4o"
        assert t.priority == 0
        assert t.weight == 1
        assert t.max_requests_per_minute is None
        assert t.enabled is True

    def test_weight_must_be_positive(self) -> None:
        with pytest.raises(Exception):
            ComboTarget(provider_id="x", model="y", weight=0)

    def test_disabled_target(self) -> None:
        t = ComboTarget(provider_id="x", model="y", enabled=False)
        assert not t.enabled


class TestComboConfig:
    def test_empty_combo_is_valid(self) -> None:
        c = ComboConfig()
        assert c.is_empty
        assert c.enabled_targets == []

    def test_default_strategy_is_priority(self) -> None:
        c = ComboConfig()
        assert c.strategy == RoutingStrategy.PRIORITY

    def test_enabled_targets_filters_disabled(self) -> None:
        c = ComboConfig(
            targets=[
                ComboTarget(provider_id="a", model="m1"),
                ComboTarget(provider_id="b", model="m2", enabled=False),
                ComboTarget(provider_id="c", model="m3"),
            ]
        )
        assert len(c.enabled_targets) == 2
        assert c.enabled_targets[0].provider_id == "a"
        assert c.enabled_targets[1].provider_id == "c"

    def test_max_retries_bounds(self) -> None:
        with pytest.raises(Exception):
            ComboConfig(max_retries=0)
        with pytest.raises(Exception):
            ComboConfig(max_retries=11)

    def test_retry_on_status_default(self) -> None:
        c = ComboConfig()
        assert 429 in c.retry_on_status
        assert 503 in c.retry_on_status

    def test_serialization_roundtrip(self) -> None:
        c = ComboConfig(
            name="Test Combo",
            targets=[
                ComboTarget(provider_id="openai", model="gpt-4o", priority=0),
                ComboTarget(provider_id="anthropic", model="claude-3.5-sonnet", priority=1),
            ],
            strategy=RoutingStrategy.LKGP,
        )
        data = c.model_dump()
        c2 = ComboConfig.model_validate(data)
        assert c2.name == "Test Combo"
        assert len(c2.targets) == 2
        assert c2.strategy == RoutingStrategy.LKGP
