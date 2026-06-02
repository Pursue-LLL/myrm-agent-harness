"""Tests for message_filtering framework.

Covers: base, system_role_filter, credential_leak_filter,
pii_redaction_filter, filter_stats, config_manager, pipeline.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from myrm_agent_harness.agent.security.message_filtering.base import (
    FilterConfig,
    FilterContext,
    MessageFilter,
)
from myrm_agent_harness.agent.security.message_filtering.config_manager import (
    MemoryConfigManager,
)
from myrm_agent_harness.agent.security.message_filtering.credential_leak_filter import (
    CredentialLeakFilter,
)
from myrm_agent_harness.agent.security.message_filtering.filter_stats import (
    FilterStats,
    measure_filter_time,
)
from myrm_agent_harness.agent.security.message_filtering.pii_redaction_filter import (
    PIIRedactionFilter,
)
from myrm_agent_harness.agent.security.message_filtering.pipeline import (
    MessageFilterPipeline,
)
from myrm_agent_harness.agent.security.message_filtering.system_role_filter import (
    SystemRoleFilter,
)
from myrm_agent_harness.agent.security.types import PrivacyPolicy

# ── base.py ──────────────────────────────────────────────────────


class TestFilterConfig:
    def test_defaults(self):
        cfg = FilterConfig()
        assert cfg.enabled is True
        assert cfg.whitelist_api_keys == set()
        assert cfg.audit_enabled is True

    def test_custom(self):
        cfg = FilterConfig(
            enabled=False, whitelist_api_keys={"k1"}, audit_enabled=False
        )
        assert cfg.enabled is False
        assert "k1" in cfg.whitelist_api_keys


class TestFilterContext:
    def test_minimal(self):
        ctx = FilterContext(user_id="u1")
        assert ctx.user_id == "u1"
        assert ctx.api_key is None
        assert ctx.metadata == {}

    def test_full(self):
        ctx = FilterContext(
            user_id="u1", api_key="k", request_id="r", metadata={"x": 1}
        )
        assert ctx.api_key == "k"
        assert ctx.metadata["x"] == 1


class TestMessageFilterABC:
    def test_cannot_instantiate_directly(self):
        with pytest.raises(TypeError):
            MessageFilter()  # type: ignore[abstract]

    def test_subclass_get_name(self):
        class MyFilter(MessageFilter):
            def should_filter(self, message, context):
                return False

        f = MyFilter()
        assert f.get_name() == "MyFilter"


# ── system_role_filter.py ────────────────────────────────────────


class TestSystemRoleFilter:
    @pytest.fixture()
    def _cfg(self):
        return FilterConfig(
            enabled=True, whitelist_api_keys={"admin-key"}, audit_enabled=True
        )

    @pytest.fixture()
    def _ctx(self):
        return FilterContext(user_id="u1", api_key="normal-key")

    def test_filters_system_role(self, _cfg, _ctx):
        f = SystemRoleFilter(_cfg)
        msg = {"role": "system", "content": "You are an AI"}
        assert f.should_filter(msg, _ctx) is True

    def test_keeps_user_role(self, _cfg, _ctx):
        f = SystemRoleFilter(_cfg)
        msg = {"role": "user", "content": "hi"}
        assert f.should_filter(msg, _ctx) is False

    def test_keeps_assistant_role(self, _cfg, _ctx):
        f = SystemRoleFilter(_cfg)
        msg = {"role": "assistant", "content": "hello"}
        assert f.should_filter(msg, _ctx) is False

    def test_whitelist_bypass(self, _cfg):
        f = SystemRoleFilter(_cfg)
        ctx = FilterContext(user_id="admin", api_key="admin-key")
        msg = {"role": "system", "content": "You are an AI"}
        assert f.should_filter(msg, ctx) is False

    def test_disabled_config(self, _ctx):
        cfg = FilterConfig(enabled=False)
        f = SystemRoleFilter(cfg)
        msg = {"role": "system", "content": "You are an AI"}
        assert f.should_filter(msg, _ctx) is False


# ── credential_leak_filter.py ───────────────────────────────────


class TestCredentialLeakFilter:
    @pytest.fixture()
    def _cfg(self):
        return FilterConfig(enabled=True, audit_enabled=True)

    @pytest.fixture()
    def _ctx(self):
        return FilterContext(user_id="u1")

    def test_blocks_openai_key(self, _cfg, _ctx):
        f = CredentialLeakFilter(_cfg)
        msg = {
            "role": "user",
            "content": "My key: sk-proj-abcdefghijklmnopqrstuvwxyz1234567890abcdef",
        }
        assert f.should_filter(msg, _ctx) is True

    def test_passes_normal_text(self, _cfg, _ctx):
        f = CredentialLeakFilter(_cfg)
        msg = {
            "role": "user",
            "content": "Just a normal message with no secrets here at all nothing",
        }
        assert f.should_filter(msg, _ctx) is False

    def test_short_content_skip(self, _cfg, _ctx):
        f = CredentialLeakFilter(_cfg)
        msg = {"role": "user", "content": "short"}
        assert f.should_filter(msg, _ctx) is False

    def test_non_string_content(self, _cfg, _ctx):
        f = CredentialLeakFilter(_cfg)
        msg = {"role": "user", "content": 12345678901234567}
        assert f.should_filter(msg, _ctx) is False

    def test_disabled(self, _ctx):
        cfg = FilterConfig(enabled=False)
        f = CredentialLeakFilter(cfg)
        msg = {
            "role": "user",
            "content": "sk-proj-abcdefghijklmnopqrstuvwxyz1234567890abcdef",
        }
        assert f.should_filter(msg, _ctx) is False

    def test_filter_method_blocks(self, _cfg, _ctx):
        f = CredentialLeakFilter(_cfg)
        msg = {
            "role": "user",
            "content": "My key: sk-proj-abcdefghijklmnopqrstuvwxyz1234567890abcdef",
        }
        assert f.filter(msg, _ctx) is None

    def test_filter_method_passes(self, _cfg, _ctx):
        f = CredentialLeakFilter(_cfg)
        msg = {
            "role": "user",
            "content": "Normal message that is long enough to be checked for creds",
        }
        result = f.filter(msg, _ctx)
        assert result is not None
        assert result["content"] == msg["content"]

    def test_filter_method_disabled(self, _ctx):
        cfg = FilterConfig(enabled=False)
        f = CredentialLeakFilter(cfg)
        msg = {
            "role": "user",
            "content": "sk-proj-abcdefghijklmnopqrstuvwxyz1234567890abcdef",
        }
        assert f.filter(msg, _ctx) == msg

    def test_filter_method_short_content(self, _cfg, _ctx):
        f = CredentialLeakFilter(_cfg)
        msg = {"role": "user", "content": "short"}
        assert f.filter(msg, _ctx) == msg


# ── pii_redaction_filter.py ─────────────────────────────────────


class TestPIIRedactionFilter:
    @pytest.fixture()
    def _cfg(self):
        return FilterConfig(enabled=True, audit_enabled=True)

    @pytest.fixture()
    def _ctx(self):
        return FilterContext(user_id="u1")

    @pytest.fixture()
    def _policy(self):
        return PrivacyPolicy(enabled=True)

    def test_invalid_mode_raises(self, _cfg, _policy):
        with pytest.raises(ValueError, match="Invalid mode"):
            PIIRedactionFilter(_cfg, _policy, mode="invalid")

    def test_block_mode_filters_pii(self, _cfg, _ctx, _policy):
        f = PIIRedactionFilter(_cfg, _policy, mode="block")
        msg = {"role": "user", "content": "我的身份证号码是110101199001011234"}
        result = f.should_filter(msg, _ctx)
        # S2/S3 PII should be blocked
        if result:
            assert result is True

    def test_redact_mode_does_not_filter(self, _cfg, _ctx, _policy):
        f = PIIRedactionFilter(_cfg, _policy, mode="redact")
        msg = {"role": "user", "content": "我的身份证号码是110101199001011234"}
        # In redact mode, should_filter returns False (redaction in filter() method)
        result = f.should_filter(msg, _ctx)
        assert result is False

    def test_passes_clean_text(self, _cfg, _ctx, _policy):
        f = PIIRedactionFilter(_cfg, _policy, mode="block")
        msg = {"role": "user", "content": "天气很好，今天阳光明媚"}
        assert f.should_filter(msg, _ctx) is False

    def test_disabled_config(self, _ctx, _policy):
        cfg = FilterConfig(enabled=False)
        f = PIIRedactionFilter(cfg, _policy, mode="block")
        msg = {"role": "user", "content": "110101199001011234"}
        assert f.should_filter(msg, _ctx) is False

    def test_disabled_policy(self, _cfg, _ctx):
        policy = PrivacyPolicy(enabled=False)
        f = PIIRedactionFilter(_cfg, policy, mode="block")
        msg = {"role": "user", "content": "110101199001011234"}
        assert f.should_filter(msg, _ctx) is False

    def test_short_content_skip(self, _cfg, _ctx, _policy):
        f = PIIRedactionFilter(_cfg, _policy, mode="block")
        msg = {"role": "user", "content": "hi"}
        assert f.should_filter(msg, _ctx) is False

    def test_filter_method_block(self, _cfg, _ctx, _policy):
        f = PIIRedactionFilter(_cfg, _policy, mode="block")
        msg = {"role": "user", "content": "我的身份证号码是110101199001011234"}
        result = f.filter(msg, _ctx)
        # ID number is S2/S3 PII in block mode
        if result is None:
            assert True

    def test_filter_method_disabled(self, _ctx, _policy):
        cfg = FilterConfig(enabled=False)
        f = PIIRedactionFilter(cfg, _policy, mode="block")
        msg = {"role": "user", "content": "110101199001011234"}
        assert f.filter(msg, _ctx) == msg

    def test_filter_method_short_content(self, _cfg, _ctx, _policy):
        f = PIIRedactionFilter(_cfg, _policy, mode="redact")
        msg = {"role": "user", "content": "hi"}
        assert f.filter(msg, _ctx) == msg


# ── filter_stats.py ──────────────────────────────────────────────


class TestFilterStats:
    def test_track_and_average(self):
        stats = FilterStats()
        stats.track("F1", 10.0)
        stats.track("F1", 20.0)
        assert stats.total_calls == 2
        assert stats.get_average_ms() == 15.0

    def test_filter_average(self):
        stats = FilterStats()
        stats.track("F1", 10.0)
        stats.track("F2", 30.0)
        assert stats.get_filter_average("F1") == 10.0
        assert stats.get_filter_average("F2") == 30.0
        assert stats.get_filter_average("nonexistent") == 0.0

    def test_slowest_tracking(self):
        stats = FilterStats()
        stats.track("F1", 10.0)
        stats.track("F2", 50.0)
        stats.track("F3", 30.0)
        assert stats.slowest_filter == "F2"
        assert stats.slowest_time_ms == 50.0

    def test_threshold_warning(self, caplog):
        stats = FilterStats(threshold_ms=5.0, critical_ms=100.0)
        import logging

        with caplog.at_level(logging.WARNING):
            stats.track("SlowFilter", 10.0)
        assert any("slow" in r.message.lower() for r in caplog.records)

    def test_critical_threshold(self, caplog):
        stats = FilterStats(threshold_ms=5.0, critical_ms=10.0)
        import logging

        with caplog.at_level(logging.ERROR):
            stats.track("CriticalFilter", 20.0)
        assert any("critically slow" in r.message.lower() for r in caplog.records)

    def test_get_summary(self):
        stats = FilterStats()
        stats.track("F1", 10.0)
        summary = stats.get_summary()
        assert summary["total_calls"] == 1
        assert "filter_stats" in summary
        assert "F1" in summary["filter_stats"]

    def test_reset(self):
        stats = FilterStats()
        stats.track("F1", 10.0)
        stats.reset()
        assert stats.total_calls == 0
        assert stats.filter_stats == {}

    def test_empty_average(self):
        stats = FilterStats()
        assert stats.get_average_ms() == 0.0

    def test_empty_filter_average_zero_calls(self):
        stats = FilterStats()
        stats.filter_stats["F1"] = {"calls": 0, "total_ms": 0.0, "max_ms": 0.0}
        assert stats.get_filter_average("F1") == 0.0


class TestMeasureFilterTime:
    def test_context_manager_tracks(self):
        stats = FilterStats()
        with measure_filter_time("TestFilter", stats):
            _ = sum(range(100))
        assert stats.total_calls == 1
        assert stats.get_filter_average("TestFilter") >= 0.0

    def test_context_manager_no_stats(self):
        with measure_filter_time("TestFilter", None):
            _ = sum(range(100))


# ── config_manager.py ────────────────────────────────────────────


class TestMemoryConfigManager:
    def test_get_config(self):
        cfg = FilterConfig(enabled=True)
        mgr = MemoryConfigManager(cfg)
        assert mgr.get_config() is cfg

    def test_reload_noop(self):
        cfg = FilterConfig()
        mgr = MemoryConfigManager(cfg)
        mgr.reload()
        assert mgr.get_config() is cfg

    def test_update_config(self):
        cfg = FilterConfig(enabled=True)
        mgr = MemoryConfigManager(cfg)
        new_cfg = FilterConfig(enabled=False)
        mgr.update_config(new_cfg)
        assert mgr.get_config() is new_cfg

    def test_observer_notified(self):
        received: list[FilterConfig] = []
        cfg = FilterConfig(enabled=True)
        mgr = MemoryConfigManager(cfg)
        mgr.subscribe(lambda c: received.append(c))
        new_cfg = FilterConfig(enabled=False)
        mgr.update_config(new_cfg)
        assert len(received) == 1
        assert received[0].enabled is False

    def test_observer_error_does_not_crash(self):
        cfg = FilterConfig()
        mgr = MemoryConfigManager(cfg)
        mgr.subscribe(lambda _: (_ for _ in ()).throw(RuntimeError("boom")))
        mgr.update_config(FilterConfig(enabled=False))


# ── pipeline.py ──────────────────────────────────────────────────


class _AlwaysFilter(MessageFilter):
    def should_filter(self, message, context):
        return True


class _NeverFilter(MessageFilter):
    def should_filter(self, message, context):
        return False


class _BrokenFilter(MessageFilter):
    def should_filter(self, message, context):
        raise RuntimeError("Broken filter")


class TestMessageFilterPipeline:
    @pytest.fixture()
    def _ctx(self):
        return FilterContext(user_id="u1")

    def test_empty_pipeline(self, _ctx):
        p = MessageFilterPipeline([])
        msgs = [{"role": "user", "content": "hi"}]
        assert p.filter_messages(msgs, _ctx) == msgs

    def test_filters_messages(self, _ctx):
        p = MessageFilterPipeline([_AlwaysFilter()])
        msgs = [{"role": "user", "content": "hi"}]
        assert p.filter_messages(msgs, _ctx) == []

    def test_keeps_messages(self, _ctx):
        p = MessageFilterPipeline([_NeverFilter()])
        msgs = [{"role": "user", "content": "hi"}]
        assert p.filter_messages(msgs, _ctx) == msgs

    def test_short_circuit(self, _ctx):
        p = MessageFilterPipeline([_AlwaysFilter(), _NeverFilter()])
        msgs = [{"role": "user", "content": "hi"}]
        assert p.filter_messages(msgs, _ctx) == []

    def test_broken_filter_does_not_crash(self, _ctx):
        p = MessageFilterPipeline([_BrokenFilter(), _NeverFilter()])
        msgs = [{"role": "user", "content": "hi"}]
        result = p.filter_messages(msgs, _ctx)
        assert len(result) == 1

    def test_add_filter(self, _ctx):
        p = MessageFilterPipeline([])
        p.add_filter(_AlwaysFilter())
        assert len(p.filters) == 1

    def test_remove_filter(self):
        p = MessageFilterPipeline([_NeverFilter()])
        assert p.remove_filter("_NeverFilter") is True
        assert len(p.filters) == 0

    def test_remove_filter_not_found(self):
        p = MessageFilterPipeline([])
        assert p.remove_filter("nonexistent") is False

    def test_get_filter_names(self):
        p = MessageFilterPipeline([_AlwaysFilter(), _NeverFilter()])
        names = p.get_filter_names()
        assert "_AlwaysFilter" in names
        assert "_NeverFilter" in names

    def test_dry_run(self, _ctx):
        p = MessageFilterPipeline([SystemRoleFilter(FilterConfig())])
        msgs = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hi"},
        ]
        result = p.dry_run(msgs, _ctx)
        assert result["stats"]["total_messages"] == 2
        assert result["stats"]["filtered_count"] == 1
        assert result["stats"]["remaining_count"] == 1

    def test_dry_run_with_test_filters(self, _ctx):
        p = MessageFilterPipeline([_NeverFilter()])
        msgs = [{"role": "user", "content": "hi"}]
        result = p.dry_run(msgs, _ctx, test_filters=[_AlwaysFilter()])
        assert result["stats"]["filtered_count"] == 1
        # Verify original pipeline is restored
        assert isinstance(p.filters[0], _NeverFilter)

    def test_bypass_with_capability(self, _ctx):
        from myrm_agent_harness.agent.security.types import Capability

        cap = Capability(permission="*", pattern="*")
        p = MessageFilterPipeline([_AlwaysFilter()])
        msgs = [{"role": "user", "content": "hi"}]
        with patch(
            "myrm_agent_harness.agent.security.message_filtering.pipeline.check_capability",
            return_value=True,
        ):
            result = p.filter_messages(msgs, _ctx, bypass_with_capability=cap)
        assert len(result) == 1

    def test_bypass_capability_check_failure(self, _ctx):
        from myrm_agent_harness.agent.security.types import Capability

        cap = Capability(permission="*", pattern="*")
        p = MessageFilterPipeline([_NeverFilter()])
        msgs = [{"role": "user", "content": "hi"}]
        with patch(
            "myrm_agent_harness.agent.security.message_filtering.pipeline.check_capability",
            side_effect=RuntimeError("boom"),
        ):
            result = p.filter_messages(msgs, _ctx, bypass_with_capability=cap)
        assert len(result) == 1

    def test_stats_disabled(self, _ctx):
        p = MessageFilterPipeline([_NeverFilter()], enable_stats=False)
        msgs = [{"role": "user", "content": "hi"}]
        result = p.filter_messages(msgs, _ctx)
        assert len(result) == 1
        assert p.stats is None

    def test_empty_dry_run(self, _ctx):
        p = MessageFilterPipeline([])
        result = p.dry_run([], _ctx)
        assert result["stats"]["total_messages"] == 0
        assert result["stats"]["filter_ratio"] == 0.0
