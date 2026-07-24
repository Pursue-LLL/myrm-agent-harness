"""Tests for Combo routing strategy implementations."""

from __future__ import annotations

from myrm_agent_harness.toolkits.llms.routing.combo.combo_types import (
    ComboTarget,
    RoutingStrategy,
)
from myrm_agent_harness.toolkits.llms.routing.combo.strategies import (
    StrategyContext,
    apply_strategy,
)


def _make_targets() -> list[ComboTarget]:
    return [
        ComboTarget(provider_id="a", model="m1", priority=2),
        ComboTarget(provider_id="b", model="m2", priority=0),
        ComboTarget(provider_id="c", model="m3", priority=1),
    ]


class TestPriorityStrategy:
    def test_sorts_by_priority(self) -> None:
        targets = _make_targets()
        ctx = StrategyContext()
        ordered = apply_strategy(targets, RoutingStrategy.PRIORITY, ctx)
        assert [t.provider_id for t in ordered] == ["b", "c", "a"]


class TestCostOptimizedStrategy:
    def test_sorts_by_priority_as_cost_proxy(self) -> None:
        targets = _make_targets()
        ctx = StrategyContext()
        ordered = apply_strategy(targets, RoutingStrategy.COST_OPTIMIZED, ctx)
        assert ordered[0].provider_id == "b"


class TestRoundRobinStrategy:
    def test_rotates_through_targets(self) -> None:
        targets = [
            ComboTarget(provider_id="a", model="m1"),
            ComboTarget(provider_id="b", model="m2"),
            ComboTarget(provider_id="c", model="m3"),
        ]
        ctx = StrategyContext()

        r1 = apply_strategy(targets, RoutingStrategy.ROUND_ROBIN, ctx)
        assert r1[0].provider_id == "a"

        r2 = apply_strategy(targets, RoutingStrategy.ROUND_ROBIN, ctx)
        assert r2[0].provider_id == "b"

        r3 = apply_strategy(targets, RoutingStrategy.ROUND_ROBIN, ctx)
        assert r3[0].provider_id == "c"

        r4 = apply_strategy(targets, RoutingStrategy.ROUND_ROBIN, ctx)
        assert r4[0].provider_id == "a"

    def test_single_target_noop(self) -> None:
        targets = [ComboTarget(provider_id="a", model="m1")]
        ctx = StrategyContext()
        r = apply_strategy(targets, RoutingStrategy.ROUND_ROBIN, ctx)
        assert len(r) == 1


class TestRandomStrategy:
    def test_returns_all_targets(self) -> None:
        targets = _make_targets()
        ctx = StrategyContext()
        ordered = apply_strategy(targets, RoutingStrategy.RANDOM, ctx)
        assert len(ordered) == 3
        assert set(t.provider_id for t in ordered) == {"a", "b", "c"}


class TestLkgpStrategy:
    def test_sticky_on_last_good(self) -> None:
        targets = _make_targets()
        ctx = StrategyContext(lkgp_target_key="c/m3")
        ordered = apply_strategy(targets, RoutingStrategy.LKGP, ctx)
        assert ordered[0].provider_id == "c"

    def test_no_sticky_falls_through(self) -> None:
        targets = _make_targets()
        ctx = StrategyContext()
        ordered = apply_strategy(targets, RoutingStrategy.LKGP, ctx)
        assert ordered[0].provider_id == "a"

    def test_stale_sticky_falls_through(self) -> None:
        targets = _make_targets()
        ctx = StrategyContext(lkgp_target_key="gone/gone")
        ordered = apply_strategy(targets, RoutingStrategy.LKGP, ctx)
        assert ordered[0].provider_id == "a"


class TestContextRelayStrategy:
    def test_prefers_affinity_target(self) -> None:
        targets = _make_targets()
        ctx = StrategyContext(context_relay_target_key="c/m3")
        ordered = apply_strategy(targets, RoutingStrategy.CONTEXT_RELAY, ctx)
        assert ordered[0].provider_id == "c"


class TestHeadroomStrategy:
    def test_prefers_most_headroom(self) -> None:
        targets = [
            ComboTarget(provider_id="a", model="m1", max_requests_per_minute=100),
            ComboTarget(provider_id="b", model="m2", max_requests_per_minute=100),
            ComboTarget(provider_id="c", model="m3"),  # no cap = infinite
        ]
        ctx = StrategyContext(
            request_counts={"a/m1": 80, "b/m2": 10},
        )
        ordered = apply_strategy(targets, RoutingStrategy.HEADROOM, ctx)
        assert ordered[0].provider_id == "c"
        assert ordered[1].provider_id == "b"  # 90 headroom
        assert ordered[2].provider_id == "a"  # 20 headroom

    def test_no_rpm_targets_are_equal(self) -> None:
        targets = [
            ComboTarget(provider_id="a", model="m1"),
            ComboTarget(provider_id="b", model="m2"),
        ]
        ctx = StrategyContext()
        ordered = apply_strategy(targets, RoutingStrategy.HEADROOM, ctx)
        assert len(ordered) == 2
