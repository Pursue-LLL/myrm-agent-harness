"""Test search provider quota telemetry and browser compute/network runtime telemetry."""

import time

from myrm_agent_harness.toolkits.browser.observability import (
    BrowserObservability,
    BrowserRunTelemetry,
    RecordingConfig,
)
from myrm_agent_harness.toolkits.web_search.core.metrics import WebSearchMetrics


class TestSearchQuotaMetrics:
    """Tests for WebSearchMetrics provider-specific quota tracking."""

    def test_record_provider_search_success_and_failures(self) -> None:
        metrics = WebSearchMetrics()
        metrics.record_provider_search("tavily", success=True, quota_exceeded=False)
        metrics.record_provider_search("tavily", success=True, quota_exceeded=False)
        metrics.record_provider_search("tavily", success=False, quota_exceeded=True)
        metrics.record_provider_search("brave", success=True, quota_exceeded=False)

        snap = metrics.snapshot()
        provider_attempts = snap.get("provider_attempts")
        provider_successes = snap.get("provider_successes")
        provider_quota_exceeded = snap.get("provider_quota_exceeded")

        assert isinstance(provider_attempts, dict)
        assert isinstance(provider_successes, dict)
        assert isinstance(provider_quota_exceeded, dict)

        assert provider_attempts.get("tavily") == 3
        assert provider_successes.get("tavily") == 2
        assert provider_quota_exceeded.get("tavily") == 1

        assert provider_attempts.get("brave") == 1
        assert provider_successes.get("brave") == 1
        assert provider_quota_exceeded.get("brave", 0) == 0


class TestBrowserRunTelemetry:
    """Tests for BrowserRunTelemetry runtime cost and network metering."""

    def test_telemetry_recording_and_snapshot(self) -> None:
        telemetry = BrowserRunTelemetry()
        assert telemetry.total_duration_seconds >= 0.0

        telemetry.record_compute(1.25)
        telemetry.record_transfer(2048)
        telemetry.record_request(success=True, bytes_transferred=1024)
        telemetry.record_request(success=False, bytes_transferred=512)

        snap = telemetry.snapshot()
        assert snap["active_compute_seconds"] == 1.25
        assert snap["total_bytes_transferred"] == 2048 + 1024 + 512
        assert snap["request_count"] == 2
        assert snap["failed_request_count"] == 1

        telemetry.mark_closed()
        assert telemetry.end_time is not None
        assert telemetry.end_time >= telemetry.start_time

    def test_browser_observability_integration(self) -> None:
        config = RecordingConfig(enabled=False)
        obs = BrowserObservability(recording_config=config)
        assert isinstance(obs.telemetry, BrowserRunTelemetry)

        obs.telemetry.record_compute(0.5)
        assert obs.telemetry.active_compute_seconds == 0.5
