"""Test search provider quota telemetry and browser compute/network runtime telemetry."""

from __future__ import annotations

import concurrent.futures
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from myrm_agent_harness.toolkits.browser.observability import (
    BrowserObservability,
    BrowserRunTelemetry,
    RecordingConfig,
)
from myrm_agent_harness.toolkits.browser.session.network_logger import NetworkLogger
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

    def test_all_base_metric_counters(self) -> None:
        """Verify all baseline WebSearchMetrics counters."""
        metrics = WebSearchMetrics()
        metrics.record_attempt()
        metrics.record_success()
        metrics.record_terminal_failure()
        metrics.record_retry_scheduled()
        metrics.record_reranker_degraded()
        metrics.record_fallback_triggered()
        metrics.record_fallback_success()
        metrics.record_fallback_failure()
        metrics.record_chain_hop(from_provider="tavily", to_provider="brave")

        snap = metrics.snapshot()
        assert snap["search_attempts"] == 1
        assert snap["search_successes"] == 1
        assert snap["search_terminal_failures"] == 1
        assert snap["search_retry_scheduled"] == 1
        assert snap["reranker_degraded_count"] == 1
        assert snap["fallback_triggered_count"] == 1
        assert snap["fallback_successes"] == 1
        assert snap["fallback_failures"] == 1
        assert snap["chain_hop_count"] == 1

    def test_concurrent_provider_recording_thread_safety(self) -> None:
        """Verify thread-safety when multiple worker threads record searches concurrently."""
        metrics = WebSearchMetrics()
        num_threads = 8
        ops_per_thread = 50

        def worker(provider_name: str) -> None:
            for i in range(ops_per_thread):
                metrics.record_provider_search(
                    provider_name,
                    success=(i % 2 == 0),
                    quota_exceeded=(i == 49),
                )

        with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = [
                executor.submit(worker, "tavily" if i % 2 == 0 else "brave")
                for i in range(num_threads)
            ]
            concurrent.futures.wait(futures)

        snap = metrics.snapshot()
        attempts = snap["provider_attempts"]
        assert attempts["tavily"] == (num_threads // 2) * ops_per_thread
        assert attempts["brave"] == (num_threads // 2) * ops_per_thread


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

        # Test mark_closed idempotency
        closed_first = telemetry.end_time
        telemetry.mark_closed()
        assert telemetry.end_time == closed_first

    def test_boundary_negative_values_defended(self) -> None:
        """Verify negative values do not corrupt telemetry state."""
        telemetry = BrowserRunTelemetry()
        telemetry.record_compute(-5.0)
        telemetry.record_transfer(-1024)
        telemetry.record_request(success=True, bytes_transferred=-500)

        assert telemetry.active_compute_seconds == 0.0
        assert telemetry.total_bytes_transferred == 0
        assert telemetry.request_count == 1

    def test_browser_observability_full_suite(self, tmp_path: Path) -> None:
        config = RecordingConfig(enabled=True, output_dir=str(tmp_path), save_on_success=True)
        obs = BrowserObservability(recording_config=config)
        assert obs.recording_enabled is True
        assert obs.video_path is None

        kwargs = obs.get_context_kwargs()
        assert "record_video_dir" in kwargs

        # Disabled config kwargs
        disabled_obs = BrowserObservability(RecordingConfig(enabled=False))
        assert disabled_obs.get_context_kwargs() == {}
        disabled_obs.cleanup_recording()

        # Telemetry
        obs.telemetry.record_compute(0.5)
        assert obs.telemetry.active_compute_seconds == 0.5

        # Check action watchdog
        now = time.monotonic()
        assert obs.check_action_watchdog(now, timeout_seconds=10.0) is True
        assert obs.check_action_watchdog(now - 20.0, timeout_seconds=10.0) is False

        # Task status & cleanup
        obs.mark_task_status(success=True)
        dummy_vid = tmp_path / "test.webm"
        dummy_vid.write_text("video-bytes")
        obs.cleanup_recording(dummy_vid)
        assert obs.video_path == dummy_vid

    @pytest.mark.asyncio
    async def test_progress_notification(self) -> None:
        mock_cb = AsyncMock()
        obs = BrowserObservability(RecordingConfig(), progress_callback=mock_cb)
        await obs.notify_progress("Processing...")
        mock_cb.assert_awaited_once_with("Processing...")

    def test_attach_to_context_listeners(self) -> None:
        obs = BrowserObservability(RecordingConfig())
        mock_ctx = MagicMock()
        obs.attach_to_context(mock_ctx)
        assert mock_ctx.on.call_count == 3

    def test_network_logger_resilient_content_length(self) -> None:
        """Verify NetworkLogger gracefully handles invalid or missing Content-Length."""
        telemetry = BrowserRunTelemetry()
        logger = NetworkLogger(telemetry=telemetry)

        mock_req = MagicMock()
        mock_req.method = "GET"
        mock_req.url = "https://test.local"
        mock_req.resource_type = "fetch"
        mock_req.post_data = None

        mock_resp = MagicMock()
        mock_resp.request = mock_req
        mock_resp.status = 200
        mock_resp.status_text = "OK"
        mock_resp.headers = {"content-length": "invalid-int-not-a-number"}

        logger._on_request(mock_req)
        logger._on_response(mock_resp)

        assert telemetry.request_count == 1
        assert telemetry.total_bytes_transferred == 0
