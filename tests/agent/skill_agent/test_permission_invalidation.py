"""Behavioral tests for the permission-invalidation hook.

``set_permission_invalidation_callback`` registers the business-layer cache
clear; ``invalidate_permissions`` triggers it after a revoke. Verifies the
call-through, the no-callback fallback, the exception guard, and unregister.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from myrm_agent_harness.agent.skill_agent.context import (
    invalidate_permissions,
    set_permission_invalidation_callback,
)


@pytest.fixture(autouse=True)
def _reset_callback() -> None:
    set_permission_invalidation_callback(None)
    yield
    set_permission_invalidation_callback(None)


def test_invalidate_permissions_invokes_registered_callback() -> None:
    callback = MagicMock()
    set_permission_invalidation_callback(callback)
    invalidate_permissions("user-1", "skill-1")
    callback.assert_called_once_with("user-1", "skill-1")


def test_invalidate_permissions_without_callback_is_noop() -> None:
    # No callback registered — must not raise; falls back to a warning log.
    invalidate_permissions("user-1", "skill-1")


def test_invalidate_permissions_swallows_callback_exception() -> None:
    def _broken(user_id: str, skill_id: str) -> None:
        raise RuntimeError("cache backend down")

    set_permission_invalidation_callback(_broken)
    # Must not propagate; the failure is logged by the framework.
    invalidate_permissions("user-1", "skill-1")


def test_unregister_callback_disables_invalidation() -> None:
    callback = MagicMock()
    set_permission_invalidation_callback(callback)
    set_permission_invalidation_callback(None)
    invalidate_permissions("user-1", "skill-1")
    callback.assert_not_called()
