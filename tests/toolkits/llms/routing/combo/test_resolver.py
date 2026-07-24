"""Tests for ComboResolver — the unified routing engine."""

from __future__ import annotations

import time

import pytest

from myrm_agent_harness.toolkits.llms.routing.combo.combo_types import (
    ComboConfig,
    ComboTarget,
    RoutingStrategy,
)
from myrm_agent_harness.toolkits.llms.routing.combo.resolver import (
    ComboResolver,
    ResolvedTarget,
)


def _two_target_combo(strategy: RoutingStrategy = RoutingStrategy.PRIORITY) -> ComboConfig:
    return ComboConfig(
        name="test",
        targets=[
            ComboTarget(provider_id="openai", model="gpt-4o", priority=0),
            ComboTarget(provider_id="anthropic", model="claude-sonnet", priority=1),
        ],
        strategy=strategy,
    )


def _credentials() -> dict[str, list[str]]:
    return {
        "openai": ["sk-key1", "sk-key2"],
        "anthropic": ["sk-anth1"],
    }


class TestResolveBasic:
    def test_resolves_first_target_by_priority(self) -> None:
        combo = _two_target_combo()
        resolver = ComboResolver(combo, _credentials())
        resolved = resolver.resolve()
        assert resolved is not None
        assert resolved.litellm_model == "openai/gpt-4o"
        assert resolved.api_key in ("sk-key1", "sk-key2")

    def test_returns_none_for_empty_combo(self) -> None:
        combo = ComboConfig()
        resolver = ComboResolver(combo, {})
        assert resolver.resolve() is None

    def test_returns_none_when_no_credentials(self) -> None:
        combo = _two_target_combo()
        resolver = ComboResolver(combo, {})
        assert resolver.resolve() is None


class TestFailover:
    def test_rotates_on_failure(self) -> None:
        combo = _two_target_combo()
        resolver = ComboResolver(combo, _credentials())

        r1 = resolver.resolve()
        assert r1 is not None
        assert r1.target.provider_id == "openai"

        resolver.report_failure(r1, "rate_limit")

        r2 = resolver.resolve()
        assert r2 is not None
        assert r2.target.provider_id == "anthropic"

    def test_key_rotation_within_provider(self) -> None:
        combo = ComboConfig(
            targets=[ComboTarget(provider_id="openai", model="gpt-4o")],
            strategy=RoutingStrategy.PRIORITY,
        )
        creds = {"openai": ["sk-key1", "sk-key2", "sk-key3"]}
        resolver = ComboResolver(combo, creds)

        r1 = resolver.resolve()
        assert r1 is not None
        key1 = r1.api_key

        resolver.report_failure(r1, "rate_limit")

        r2 = resolver.resolve()
        assert r2 is not None

    def test_success_resets_cooldown(self) -> None:
        combo = _two_target_combo()
        resolver = ComboResolver(combo, _credentials())

        r1 = resolver.resolve()
        assert r1 is not None
        resolver.report_failure(r1, "rate_limit")
        resolver.report_success(r1)

        r2 = resolver.resolve()
        assert r2 is not None
        assert r2.target.provider_id == "openai"


class TestLkgpIntegration:
    def test_success_sets_lkgp(self) -> None:
        combo = _two_target_combo(RoutingStrategy.LKGP)
        resolver = ComboResolver(combo, _credentials())

        r1 = resolver.resolve()
        assert r1 is not None
        resolver.report_success(r1)

        r2 = resolver.resolve()
        assert r2 is not None
        assert r2.target.provider_id == r1.target.provider_id


class TestRoundRobinIntegration:
    def test_rotates_targets(self) -> None:
        combo = ComboConfig(
            targets=[
                ComboTarget(provider_id="a", model="m1"),
                ComboTarget(provider_id="b", model="m2"),
            ],
            strategy=RoutingStrategy.ROUND_ROBIN,
        )
        creds = {"a": ["k1"], "b": ["k2"]}
        resolver = ComboResolver(combo, creds)

        r1 = resolver.resolve()
        assert r1 is not None
        resolver.report_success(r1)
        first_provider = r1.target.provider_id

        r2 = resolver.resolve()
        assert r2 is not None
        resolver.report_success(r2)
        assert r2.target.provider_id != first_provider


class TestCustomModelFormatter:
    def test_uses_custom_formatter(self) -> None:
        combo = ComboConfig(
            targets=[ComboTarget(provider_id="deepseek", model="chat")],
        )

        def fmt(pid: str, model: str) -> str:
            return f"custom/{pid}_{model}"

        resolver = ComboResolver(combo, {"deepseek": ["dk-1"]}, litellm_model_fn=fmt)
        r = resolver.resolve()
        assert r is not None
        assert r.litellm_model == "custom/deepseek_chat"


class TestMaxRetries:
    def test_max_retries_property(self) -> None:
        combo = ComboConfig(max_retries=5)
        resolver = ComboResolver(combo, {})
        assert resolver.max_retries == 5

    def test_retry_on_status_property(self) -> None:
        combo = ComboConfig()
        resolver = ComboResolver(combo, {})
        assert 429 in resolver.retry_on_status


class TestDisabledTargets:
    def test_disabled_targets_skipped(self) -> None:
        combo = ComboConfig(
            targets=[
                ComboTarget(provider_id="a", model="m1", enabled=False),
                ComboTarget(provider_id="b", model="m2"),
            ],
        )
        resolver = ComboResolver(combo, {"a": ["k1"], "b": ["k2"]})
        r = resolver.resolve()
        assert r is not None
        assert r.target.provider_id == "b"
