"""Unit tests for SQLiteProfile presets and validation."""

from __future__ import annotations

import dataclasses

import pytest

from myrm_agent_harness.utils.db.sqlite import (
    CACHE,
    DEFAULT,
    DURABLE,
    READONLY,
    SENSITIVE,
    SQLiteProfile,
)


def test_default_preset_is_safe_general_purpose() -> None:
    assert DEFAULT.use_wal is True
    assert DEFAULT.synchronous == "NORMAL"
    assert DEFAULT.secure_delete == "FAST"
    assert DEFAULT.cell_size_check is True
    assert DEFAULT.foreign_keys is True
    assert DEFAULT.busy_timeout_ms == 5000


def test_durable_preset_enlarges_working_set() -> None:
    assert DURABLE.cache_size == -64000
    assert DURABLE.temp_store_memory is True
    assert DURABLE.mmap_size_bytes == 268_435_456
    assert DURABLE.use_wal is True


def test_sensitive_preset_zeroes_deleted_bytes() -> None:
    assert SENSITIVE.secure_delete == "ON"


def test_cache_preset_drops_privacy_cost_keeps_wal() -> None:
    assert CACHE.secure_delete == "OFF"
    assert CACHE.use_wal is True
    assert CACHE.cell_size_check is True


def test_readonly_preset_skips_journal_and_secure_delete() -> None:
    assert READONLY.read_only is True
    assert READONLY.use_wal is False
    assert READONLY.secure_delete == "OFF"


def test_profile_is_frozen() -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        DEFAULT.synchronous = "FULL"  # type: ignore[misc]


@pytest.mark.parametrize("bad", ["MAYBE", "fast", ""])
def test_invalid_synchronous_rejected(bad: str) -> None:
    with pytest.raises(ValueError, match="synchronous"):
        SQLiteProfile(synchronous=bad)


@pytest.mark.parametrize("bad", ["YES", "soft", ""])
def test_invalid_secure_delete_rejected(bad: str) -> None:
    with pytest.raises(ValueError, match="secure_delete"):
        SQLiteProfile(secure_delete=bad)


def test_negative_busy_timeout_rejected() -> None:
    with pytest.raises(ValueError, match="busy_timeout_ms"):
        SQLiteProfile(busy_timeout_ms=-1)


def test_synchronous_accepts_extra_mode() -> None:
    assert SQLiteProfile(synchronous="EXTRA").synchronous == "EXTRA"
