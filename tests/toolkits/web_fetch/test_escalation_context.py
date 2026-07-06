"""Tests for web fetch escalation context and metrics."""

from __future__ import annotations

import pytest

from myrm_agent_harness.toolkits.browser.pool.config import LaunchMode
from myrm_agent_harness.toolkits.web_fetch.escalation.context import (
    bind_web_fetch_escalation_context,
    get_bound_browser_launch_mode,
    get_bound_escalation_providers,
)
from myrm_agent_harness.toolkits.web_fetch.escalation.metrics import WebFetchEscalationMetrics
from myrm_agent_harness.toolkits.web_fetch.escalation.protocols import EscalationFetchResult


class _Provider:
    provider_id = "stub"

    async def fetch_url(self, url: str, *, max_chars: int = 0) -> EscalationFetchResult:
        return EscalationFetchResult(url=url, content="x", provider_id="stub")


def test_bind_context_sets_and_resets_providers() -> None:
    assert get_bound_escalation_providers() is None
    with bind_web_fetch_escalation_context(providers=[_Provider()], launch_mode=LaunchMode.EXTENSION):
        assert get_bound_escalation_providers() is not None
        assert get_bound_browser_launch_mode() == LaunchMode.EXTENSION
    assert get_bound_escalation_providers() is None
    assert get_bound_browser_launch_mode() is None


def test_metrics_snapshot() -> None:
    metrics = WebFetchEscalationMetrics()
    metrics.record_triggered()
    metrics.record_success()
    metrics.record_failure()
    metrics.record_session_cap_blocked()
    snap = metrics.snapshot()
    assert snap == {
        "triggered_count": 1,
        "success_count": 1,
        "failure_count": 1,
        "session_cap_blocked_count": 1,
    }
