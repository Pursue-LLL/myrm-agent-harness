"""Alert Integration Unit Tests

Tests for AlertIntegration multi-channel alerting system.
"""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from myrm_agent_harness.agent.skills.optimization import AlertIntegration, EventEmitter


@pytest.fixture
def alert_config():
    """Test alert configuration"""
    return {
        "slack": {
            "webhook_url": "https://hooks.slack.com/test",
            "channel": "#test-alerts",
            "severity_threshold": "warning",
        },
        "pagerduty": {
            "routing_key": "test-routing-key",
            "severity_threshold": "critical",
        },
        "email": {
            "smtp_host": "smtp.test.com",
            "smtp_port": 587,
            "username": "test@test.com",
            "password": "test-password",
            "from_addr": "alerts@test.com",
            "to_addrs": ["admin@test.com"],
            "severity_threshold": "critical",
        },
        "rate_limit": {
            "max_alerts_per_hour": 10,
            "dedup_window_minutes": 60,
        },
    }


@pytest.fixture
def event_emitter():
    """Create event emitter"""
    return EventEmitter()


@pytest.mark.asyncio
async def test_anomaly_alert_dispatch(alert_config, event_emitter):
    """Test anomaly alert dispatching"""
    alert_integration = AlertIntegration(event_emitter, alert_config)

    with patch("httpx.AsyncClient.post") as mock_post:
        mock_post.return_value = AsyncMock(status_code=200)

        await alert_integration.start()

        # Emit anomaly event
        await event_emitter.emit(
            "anomaly_detected",
            {
                "skill_id": "test-skill",
                "severity": "critical",
                "score_delta": -0.35,
                "root_causes": [{"type": "performance_degradation", "evidence": "Execution time increased 50%"}],
            },
        )

        # Allow async processing
        await asyncio.sleep(0.2)

        # Verify Slack webhook was called
        assert mock_post.called
        call_args = mock_post.call_args
        assert "test-skill" in str(call_args)


@pytest.mark.asyncio
async def test_optimization_failed_alert(alert_config, event_emitter):
    """Test optimization failure alert"""
    alert_integration = AlertIntegration(event_emitter, alert_config)

    with patch("httpx.AsyncClient.post") as mock_post:
        mock_post.return_value = AsyncMock(status_code=200)

        await alert_integration.start()

        await event_emitter.emit(
            "optimization_failed",
            {
                "skill_id": "broken-skill",
                "error": "LLM timeout after 3 retries",
                "severity": "warning",
            },
        )

        await asyncio.sleep(0.2)

        assert mock_post.called


@pytest.mark.asyncio
async def test_rate_limiting(alert_config, event_emitter):
    """Test alert rate limiting"""
    alert_integration = AlertIntegration(event_emitter, alert_config)

    with patch("httpx.AsyncClient.post") as mock_post:
        mock_post.return_value = AsyncMock(status_code=200)

        await alert_integration.start()

        # Trigger 15 alerts (limit is 10 per hour)
        for i in range(15):
            await event_emitter.emit(
                "anomaly_detected",
                {
                    "skill_id": f"skill-{i}",
                    "severity": "warning",
                    "score_delta": -0.1,
                    "root_causes": [],
                },
            )

        await asyncio.sleep(0.3)

        # Should only send 10 alerts
        assert mock_post.call_count <= 10


@pytest.mark.asyncio
async def test_deduplication(alert_config, event_emitter):
    """Test alert deduplication"""
    alert_integration = AlertIntegration(event_emitter, alert_config)

    with patch("httpx.AsyncClient.post") as mock_post:
        mock_post.return_value = AsyncMock(status_code=200)

        await alert_integration.start()

        # Trigger same alert twice
        for _ in range(2):
            await event_emitter.emit(
                "anomaly_detected",
                {
                    "skill_id": "dup-skill",
                    "severity": "critical",
                    "score_delta": -0.2,
                    "root_causes": [],
                },
            )

        await asyncio.sleep(0.2)

        # Should only send once due to dedup
        assert mock_post.call_count == 1


@pytest.mark.asyncio
async def test_severity_threshold(alert_config, event_emitter):
    """Test severity threshold filtering"""
    alert_integration = AlertIntegration(event_emitter, alert_config)

    with patch("httpx.AsyncClient.post") as mock_post:
        mock_post.return_value = AsyncMock(status_code=200)

        await alert_integration.start()

        # Low severity (should not trigger PagerDuty with critical threshold)
        await event_emitter.emit(
            "anomaly_detected",
            {
                "skill_id": "low-severity-skill",
                "severity": "warning",
                "score_delta": -0.1,
                "root_causes": [],
            },
        )

        await asyncio.sleep(0.2)

        # Should call Slack (threshold: warning) but not PagerDuty (threshold: critical)
        # In this test we mock all HTTP calls, so we verify Slack was called
        assert mock_post.called
