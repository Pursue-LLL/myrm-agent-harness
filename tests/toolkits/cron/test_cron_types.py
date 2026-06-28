"""Unit tests for cron domain types and serialization helpers."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from myrm_agent_harness.toolkits.cron.types import (
    ActiveHours,
    CronConfig,
    CronJob,
    CronJobPatch,
    DeliveryConfig,
    FailureAlertConfig,
    JobType,
    Schedule,
    ScheduleKind,
    SessionTarget,
    TransientErrorKind,
    active_hours_to_dict,
    dict_to_active_hours,
    dict_to_failure_alert,
    dict_to_schedule,
    failure_alert_to_dict,
    schedule_to_dict,
)

# ---------------------------------------------------------------------------
# ActiveHours
# ---------------------------------------------------------------------------


class TestActiveHours:
    def test_create(self):
        ah = ActiveHours(start="09:00", end="18:00", tz="Asia/Shanghai")
        assert ah.start == "09:00"
        assert ah.end == "18:00"
        assert ah.tz == "Asia/Shanghai"

    def test_default_tz(self):
        ah = ActiveHours(start="00:00", end="23:59")
        assert ah.tz == "UTC"

    def test_frozen(self):
        ah = ActiveHours(start="09:00", end="18:00")
        with pytest.raises(AttributeError):
            ah.start = "10:00"  # type: ignore[misc]


class TestActiveHoursSerialization:
    def test_to_dict(self):
        ah = ActiveHours(start="09:00", end="18:00", tz="UTC")
        result = active_hours_to_dict(ah)
        assert result == {"start": "09:00", "end": "18:00", "tz": "UTC"}

    def test_to_dict_none(self):
        assert active_hours_to_dict(None) is None

    def test_from_dict(self):
        d = {"start": "09:00", "end": "18:00", "tz": "Asia/Tokyo"}
        ah = dict_to_active_hours(d)
        assert ah is not None
        assert ah.start == "09:00"
        assert ah.end == "18:00"
        assert ah.tz == "Asia/Tokyo"

    def test_from_dict_none(self):
        assert dict_to_active_hours(None) is None

    def test_from_dict_empty(self):
        assert dict_to_active_hours({}) is None

    def test_from_dict_missing_fields(self):
        assert dict_to_active_hours({"start": "09:00"}) is None
        assert dict_to_active_hours({"end": "18:00"}) is None

    def test_from_dict_default_tz(self):
        d = {"start": "09:00", "end": "18:00"}
        ah = dict_to_active_hours(d)
        assert ah is not None
        assert ah.tz == "UTC"


# ---------------------------------------------------------------------------
# Schedule
# ---------------------------------------------------------------------------


class TestScheduleValidation:
    def test_cron_requires_expr(self):
        with pytest.raises(ValueError, match="requires 'expr'"):
            Schedule(kind=ScheduleKind.CRON)

    def test_interval_requires_positive_ms(self):
        with pytest.raises(ValueError, match="interval_ms must be >= 100"):
            Schedule(kind=ScheduleKind.INTERVAL, interval_ms=-1)

    def test_interval_requires_interval_ms(self):
        with pytest.raises(ValueError, match="interval_ms must be >= 100"):
            Schedule(kind=ScheduleKind.INTERVAL)

    def test_once_requires_run_at(self):
        with pytest.raises(ValueError, match="requires 'run_at'"):
            Schedule(kind=ScheduleKind.ONCE)

    def test_tz_only_for_cron(self):
        with pytest.raises(ValueError, match="'tz' only applies"):
            Schedule(kind=ScheduleKind.INTERVAL, interval_ms=60000, tz="UTC")

    def test_negative_stagger_corrected(self):
        s = Schedule(kind=ScheduleKind.CRON, expr="0 * * * *", stagger_ms=-5)
        assert s.stagger_ms == 0

    def test_valid_cron(self):
        s = Schedule(kind=ScheduleKind.CRON, expr="0 9 * * *", tz="Asia/Shanghai")
        assert s.kind == ScheduleKind.CRON
        assert s.expr == "0 9 * * *"

    def test_valid_interval(self):
        s = Schedule(kind=ScheduleKind.INTERVAL, interval_ms=300000)
        assert s.interval_ms == 300000

    def test_valid_once(self):
        now = datetime.now(UTC)
        s = Schedule(kind=ScheduleKind.ONCE, run_at=now)
        assert s.run_at == now


class TestScheduleSerialization:
    def test_roundtrip_cron(self):
        s = Schedule(kind=ScheduleKind.CRON, expr="*/5 * * * *", tz="UTC", stagger_ms=5000)
        d = schedule_to_dict(s)
        restored = dict_to_schedule(d)
        assert restored.kind == s.kind
        assert restored.expr == s.expr
        assert restored.tz == s.tz
        assert restored.stagger_ms == s.stagger_ms

    def test_roundtrip_interval(self):
        s = Schedule(kind=ScheduleKind.INTERVAL, interval_ms=600000)
        d = schedule_to_dict(s)
        restored = dict_to_schedule(d)
        assert restored.kind == s.kind
        assert restored.interval_ms == s.interval_ms


# ---------------------------------------------------------------------------
# CronJobPatch.clear_active_hours
# ---------------------------------------------------------------------------


class TestCronJobPatch:
    def test_clear_active_hours_default_false(self):
        patch = CronJobPatch()
        assert patch.clear_active_hours is False

    def test_clear_active_hours_true(self):
        patch = CronJobPatch(clear_active_hours=True)
        assert patch.clear_active_hours is True
        assert patch.active_hours is None

    def test_active_hours_set(self):
        ah = ActiveHours(start="09:00", end="18:00")
        patch = CronJobPatch(active_hours=ah)
        assert patch.active_hours == ah
        assert patch.clear_active_hours is False

    def test_clear_max_fires_default_false(self):
        patch = CronJobPatch()
        assert patch.clear_max_fires is False

    def test_clear_max_fires_true(self):
        patch = CronJobPatch(clear_max_fires=True)
        assert patch.clear_max_fires is True
        assert patch.max_fires is None

    def test_max_fires_set(self):
        patch = CronJobPatch(max_fires=10)
        assert patch.max_fires == 10
        assert patch.clear_max_fires is False

    def test_clear_expires_at(self):
        patch = CronJobPatch(clear_expires_at=True)
        assert patch.clear_expires_at is True
        assert patch.expires_at is None

    def test_expires_at_set(self):
        dt = datetime(2026, 12, 31, tzinfo=UTC)
        patch = CronJobPatch(expires_at=dt)
        assert patch.expires_at == dt
        assert patch.clear_expires_at is False

    def test_clear_failure_alert(self):
        patch = CronJobPatch(clear_failure_alert=True)
        assert patch.clear_failure_alert is True

    def test_failure_alert_set(self):
        fa = FailureAlertConfig(after=5, cooldown_seconds=600)
        patch = CronJobPatch(failure_alert=fa)
        assert patch.failure_alert == fa

    def test_failure_alert_false(self):
        patch = CronJobPatch(failure_alert=False)
        assert patch.failure_alert is False

    def test_session_target_set(self):
        patch = CronJobPatch(session_target=SessionTarget.MAIN)
        assert patch.session_target == SessionTarget.MAIN

    def test_chat_id_default_none(self):
        patch = CronJobPatch()
        assert patch.chat_id is None
        assert patch.clear_chat_id is False

    def test_chat_id_set(self):
        patch = CronJobPatch(chat_id="chat-abc")
        assert patch.chat_id == "chat-abc"
        assert patch.clear_chat_id is False

    def test_clear_chat_id_true(self):
        patch = CronJobPatch(clear_chat_id=True)
        assert patch.clear_chat_id is True
        assert patch.chat_id is None

    def test_cooldown_seconds_set(self):
        patch = CronJobPatch(cooldown_seconds=120)
        assert patch.cooldown_seconds == 120

    def test_run_retention_days_set(self):
        patch = CronJobPatch(run_retention_days=90)
        assert patch.run_retention_days == 90

    def test_clear_monitor_config(self):
        patch = CronJobPatch(clear_monitor_config=True)
        assert patch.clear_monitor_config is True

    def test_pre_condition_script_set(self):
        patch = CronJobPatch(pre_condition_script="echo ok")
        assert patch.pre_condition_script == "echo ok"
        assert patch.clear_pre_condition_script is False

    def test_clear_pre_condition_script(self):
        patch = CronJobPatch(clear_pre_condition_script=True)
        assert patch.clear_pre_condition_script is True
        assert patch.pre_condition_script is None

    def test_all_defaults(self):
        patch = CronJobPatch()
        assert patch.name is None
        assert patch.cooldown_seconds is None
        assert patch.max_fires is None
        assert patch.clear_max_fires is False
        assert patch.expires_at is None
        assert patch.clear_expires_at is False
        assert patch.session_target is None
        assert patch.run_retention_days is None
        assert patch.failure_alert is None
        assert patch.clear_failure_alert is False
        assert patch.pre_condition_script is None
        assert patch.clear_pre_condition_script is False


# ---------------------------------------------------------------------------
# SessionTarget
# ---------------------------------------------------------------------------


class TestSessionTarget:
    def test_values(self):
        assert SessionTarget.ISOLATED == "isolated"
        assert SessionTarget.MAIN == "main"
        assert SessionTarget.DAILY == "daily"

    def test_all_members(self):
        assert {e.value for e in SessionTarget} == {"isolated", "main", "daily"}

    def test_is_str_enum(self):
        assert isinstance(SessionTarget.ISOLATED, str)
        assert isinstance(SessionTarget.DAILY, str)

    def test_daily_as_default_overridable(self):
        """CronJob defaults to ISOLATED; DAILY is selectable via override."""
        defaults = {
            "id": "j1",
            "user_id": "u1",
            "name": "Test",
            "job_type": JobType.AGENT,
            "schedule": Schedule(kind=ScheduleKind.CRON, expr="0 * * * *"),
        }
        job_isolated = CronJob(**defaults)  # type: ignore[arg-type]
        assert job_isolated.session_target == SessionTarget.ISOLATED

        job_daily = CronJob(**{**defaults, "session_target": SessionTarget.DAILY})  # type: ignore[arg-type]
        assert job_daily.session_target == SessionTarget.DAILY

    def test_patch_session_target_daily(self):
        patch = CronJobPatch(session_target=SessionTarget.DAILY)
        assert patch.session_target == SessionTarget.DAILY


# ---------------------------------------------------------------------------
# TransientErrorKind
# ---------------------------------------------------------------------------


class TestTransientErrorKind:
    def test_all_values(self):
        expected = {"rate_limit", "overloaded", "network", "timeout", "server_error"}
        assert {e.value for e in TransientErrorKind} == expected


# ---------------------------------------------------------------------------
# FailureAlertConfig
# ---------------------------------------------------------------------------


class TestFailureAlertConfig:
    def test_defaults(self):
        fa = FailureAlertConfig()
        assert fa.enabled is True
        assert fa.after == 3
        assert fa.cooldown_seconds == 300
        assert fa.delivery is None

    def test_custom_values(self):
        d = DeliveryConfig(channel="webhook", target="https://alert.example.com")
        fa = FailureAlertConfig(enabled=True, after=5, cooldown_seconds=600, delivery=d)
        assert fa.after == 5
        assert fa.cooldown_seconds == 600
        assert fa.delivery is not None
        assert fa.delivery.channel == "webhook"

    def test_frozen(self):
        fa = FailureAlertConfig()
        with pytest.raises(AttributeError):
            fa.after = 10  # type: ignore[misc]

    def test_serialization_roundtrip(self):
        fa = FailureAlertConfig(after=5, cooldown_seconds=600)
        d = failure_alert_to_dict(fa)
        assert d["after"] == 5
        assert d["cooldown_seconds"] == 600
        restored = dict_to_failure_alert(d)
        assert restored is not None
        assert restored.after == fa.after
        assert restored.cooldown_seconds == fa.cooldown_seconds

    def test_serialization_none(self):
        assert failure_alert_to_dict(None) is None
        assert dict_to_failure_alert(None) is None

    def test_serialization_false(self):
        assert failure_alert_to_dict(False) is False

    def test_serialization_with_delivery(self):
        d = DeliveryConfig(channel="webhook", target="https://x.com")
        fa = FailureAlertConfig(delivery=d)
        serialized = failure_alert_to_dict(fa)
        assert serialized is not None
        assert serialized["delivery"]["channel"] == "webhook"
        restored = dict_to_failure_alert(serialized)
        assert restored is not None
        assert restored.delivery is not None
        assert restored.delivery.channel == "webhook"


# ---------------------------------------------------------------------------
# CronConfig
# ---------------------------------------------------------------------------


class TestCronConfig:
    def test_defaults(self):
        cfg = CronConfig()
        assert cfg.max_concurrent == 5
        assert cfg.max_per_user == 3
        assert cfg.failure_delivery is None
        assert cfg.failure_alert is None

    def test_custom_values(self):
        d = DeliveryConfig(channel="webhook", target="https://ops.example.com")
        fa = FailureAlertConfig(after=10)
        cfg = CronConfig(max_concurrent=10, max_per_user=5, failure_delivery=d, failure_alert=fa)
        assert cfg.max_concurrent == 10
        assert cfg.max_per_user == 5
        assert cfg.failure_delivery is not None
        assert cfg.failure_alert is not None
        assert cfg.failure_alert.after == 10

    def test_frozen(self):
        cfg = CronConfig()
        with pytest.raises(AttributeError):
            cfg.max_concurrent = 20  # type: ignore[misc]


# ---------------------------------------------------------------------------
# CronJob new fields
# ---------------------------------------------------------------------------


class TestCronJobNewFields:
    def _make_job(self, **kwargs: object) -> CronJob:
        defaults = {
            "id": "j1",
            "user_id": "u1",
            "name": "Test",
            "job_type": JobType.AGENT,
            "schedule": Schedule(kind=ScheduleKind.CRON, expr="0 * * * *"),
        }
        defaults.update(kwargs)
        return CronJob(**defaults)  # type: ignore[arg-type]

    def test_defaults(self):
        job = self._make_job()
        assert job.cooldown_seconds == 0
        assert job.max_fires is None
        assert job.expires_at is None
        assert job.fire_count == 0
        assert job.session_target == SessionTarget.ISOLATED
        assert job.failure_alert is None
        assert job.run_retention_days == 30

    def test_custom_values(self):
        dt = datetime(2026, 12, 31, tzinfo=UTC)
        fa = FailureAlertConfig(after=5)
        job = self._make_job(
            cooldown_seconds=60,
            max_fires=100,
            expires_at=dt,
            fire_count=42,
            session_target=SessionTarget.MAIN,
            failure_alert=fa,
            run_retention_days=90,
        )
        assert job.cooldown_seconds == 60
        assert job.max_fires == 100
        assert job.expires_at == dt
        assert job.fire_count == 42
        assert job.session_target == SessionTarget.MAIN
        assert job.failure_alert == fa
        assert job.run_retention_days == 90

    def test_failure_alert_false(self):
        job = self._make_job(failure_alert=False)
        assert job.failure_alert is False
