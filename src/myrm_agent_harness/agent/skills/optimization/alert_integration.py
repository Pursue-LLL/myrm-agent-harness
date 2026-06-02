from __future__ import annotations

import asyncio
import hashlib
import logging
import smtplib
from datetime import datetime, timedelta
from enum import StrEnum
from typing import TYPE_CHECKING, Any

"""Alert Integration for Skill Quality Monitoring

Integrates with external alerting systems (Slack, PagerDuty, Email) for critical
skill quality issues detected by AnomalyDetector or AutoOptimizationEngine.

[INPUT]
- .types.AnomalyReport (POS: Anomaly data)
- .event_emitter.EventEmitter (POS: Event source)

[OUTPUT]
- AlertIntegration: Alert dispatcher class

[POS]
Framework-layer alert integration for production monitoring.
Supports:
1. Multiple alert channels (Slack, PagerDuty, Email, Webhook)
2. Severity-based routing (critical -> PagerDuty, warning -> Slack)
3. Rate limiting to prevent alert storms
4. Alert deduplication (same skill, same issue within time window)
"""


if TYPE_CHECKING:
    from .event_emitter import EventEmitter

logger = logging.getLogger(__name__)


class AlertChannel(StrEnum):
    """Supported alert channels"""

    SLACK = "slack"
    PAGERDUTY = "pagerduty"
    EMAIL = "email"
    WEBHOOK = "webhook"


class AlertIntegration:
    """Alert integration dispatcher for skill quality monitoring

    Features:
    - Multi-channel routing based on severity
    - Rate limiting (max N alerts per time window)
    - Alert deduplication (same skill + same issue)
    - Async non-blocking dispatch

    Args:
        event_emitter: EventEmitter to subscribe to
        config: Alert configuration dict

    Example:
        ```python
        config = {
            "slack": {
                "webhook_url": "https://hooks.slack.com/...",
                "channel": "#alerts",
                "severity_threshold": "warning",
            },
            "pagerduty": {
                "api_key": "...",
                "service_id": "...",
                "severity_threshold": "critical",
            },
            "rate_limit": {
                "max_alerts_per_hour": 10,
                "dedup_window_minutes": 60,
            },
        }

        alert_integration = AlertIntegration(event_emitter, config)
        await alert_integration.start()
        ```
    """

    def __init__(self, event_emitter: EventEmitter, config: dict[str, Any]):
        self.event_emitter = event_emitter
        self.config = config

        self.rate_limit_max = config.get("rate_limit", {}).get("max_alerts_per_hour", 10)
        self.dedup_window_minutes = config.get("rate_limit", {}).get("dedup_window_minutes", 60)

        self._alert_timestamps: list[datetime] = []
        self._dedup_cache: dict[str, datetime] = {}

        self._channels: dict[AlertChannel, dict[str, Any]] = self._init_channels()

    def _init_channels(self) -> dict[AlertChannel, dict[str, Any]]:
        """Initialize configured alert channels"""
        channels = {}

        if "slack" in self.config:
            channels[AlertChannel.SLACK] = self.config["slack"]
            logger.info("Slack alert channel initialized")

        if "pagerduty" in self.config:
            channels[AlertChannel.PAGERDUTY] = self.config["pagerduty"]
            logger.info("PagerDuty alert channel initialized")

        if "email" in self.config:
            channels[AlertChannel.EMAIL] = self.config["email"]
            logger.info("Email alert channel initialized")

        if "webhook" in self.config:
            channels[AlertChannel.WEBHOOK] = self.config["webhook"]
            logger.info("Webhook alert channel initialized")

        return channels

    async def start(self) -> None:
        """Start listening to events"""
        self.event_emitter.on("anomaly_detected", self._on_anomaly_detected)
        self.event_emitter.on("optimization_failed", self._on_optimization_failed)
        logger.info("AlertIntegration started, subscribed to events")

    async def _on_anomaly_detected(self, event: str, payload: dict[str, Any]) -> None:
        """Handle anomaly_detected event"""
        skill_id = payload.get("skill_id", "unknown")
        severity = payload.get("severity", "warning")
        score_delta = payload.get("score_delta", 0.0)
        root_causes = payload.get("root_causes", [])

        alert_key = self._generate_dedup_key(skill_id, "anomaly", severity)

        if not self._should_send_alert(alert_key):
            logger.debug(f"Alert suppressed (rate limit or dedup): {alert_key}")
            return

        message = (
            f" Skill Quality Anomaly Detected\n"
            f"**Skill**: {skill_id}\n"
            f"**Severity**: {severity.upper()}\n"
            f"**Score Delta**: {score_delta:.2f}\n"
            f"**Root Causes**: {', '.join([c['type'] for c in root_causes])}\n"
        )

        await self._dispatch_alert(severity, message, metadata=payload)

        self._record_alert(alert_key)

    async def _on_optimization_failed(self, event: str, payload: dict[str, Any]) -> None:
        """Handle optimization_failed event"""
        skill_id = payload.get("skill_id", "unknown")
        error = payload.get("error", "Unknown error")

        alert_key = self._generate_dedup_key(skill_id, "opt_failed", "error")

        if not self._should_send_alert(alert_key):
            logger.debug(f"Alert suppressed (rate limit or dedup): {alert_key}")
            return

        message = (
            f" Skill Optimization Failed\n"
            f"**Skill**: {skill_id}\n"
            f"**Error**: {error}\n"
            f"**Action**: Manual intervention may be required\n"
        )

        await self._dispatch_alert("error", message, metadata=payload)

        self._record_alert(alert_key)

    async def _dispatch_alert(self, severity: str, message: str, metadata: dict[str, Any]) -> None:
        """Dispatch alert to appropriate channels based on severity"""
        tasks = []

        for channel, channel_config in self._channels.items():
            severity_threshold = channel_config.get("severity_threshold", "warning")

            if self._should_route_to_channel(severity, severity_threshold):
                tasks.append(self._send_to_channel(channel, channel_config, message, metadata))

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def _should_route_to_channel(self, severity: str, threshold: str) -> bool:
        """Determine if alert should be routed to channel based on severity"""
        severity_rank = {"info": 0, "warning": 1, "error": 2, "critical": 3}

        current_rank = severity_rank.get(severity, 0)
        threshold_rank = severity_rank.get(threshold, 0)

        return current_rank >= threshold_rank

    async def _send_to_channel(
        self, channel: AlertChannel, config: dict[str, Any], message: str, metadata: dict[str, Any]
    ) -> None:
        """Send alert to specific channel"""
        try:
            if channel == AlertChannel.SLACK:
                await self._send_slack(config, message, metadata)
            elif channel == AlertChannel.PAGERDUTY:
                await self._send_pagerduty(config, message, metadata)
            elif channel == AlertChannel.EMAIL:
                await self._send_email(config, message, metadata)
            elif channel == AlertChannel.WEBHOOK:
                await self._send_webhook(config, message, metadata)
        except Exception as e:
            logger.error(f"Failed to send alert to {channel.value}: {e}")

    async def _send_slack(self, config: dict[str, Any], message: str, metadata: dict[str, Any]) -> None:
        """Send alert to Slack"""
        import httpx

        webhook_url = config.get("webhook_url")
        channel = config.get("channel", "#alerts")

        if not webhook_url:
            logger.warning("Slack webhook_url not configured")
            return

        payload = {
            "channel": channel,
            "username": "Myrm Skill Monitor",
            "text": message,
            "attachments": [
                {
                    "color": "danger" if metadata.get("severity") == "critical" else "warning",
                    "fields": [
                        {"title": "Skill ID", "value": metadata.get("skill_id", "unknown"), "short": True},
                        {"title": "Timestamp", "value": datetime.now().isoformat(), "short": True},
                    ],
                }
            ],
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(webhook_url, json=payload, timeout=5.0)
            response.raise_for_status()

        logger.info(f"Alert sent to Slack channel: {channel}")

    async def _send_pagerduty(self, config: dict[str, Any], message: str, metadata: dict[str, Any]) -> None:
        """Send alert to PagerDuty"""
        import httpx

        api_key = config.get("api_key")
        service_id = config.get("service_id")

        if not api_key or not service_id:
            logger.warning("PagerDuty api_key or service_id not configured")
            return

        payload = {
            "routing_key": api_key,
            "event_action": "trigger",
            "payload": {
                "summary": message,
                "severity": metadata.get("severity", "warning"),
                "source": "myrm-skill-optimization",
                "custom_details": metadata,
            },
        }

        async with httpx.AsyncClient() as client:
            response = await client.post("https://events.pagerduty.com/v2/enqueue", json=payload, timeout=5.0)
            response.raise_for_status()

        logger.info("Alert sent to PagerDuty")

    async def _send_email(self, config: dict[str, Any], message: str, metadata: dict[str, Any]) -> None:
        """Send alert via email"""
        from email.mime.text import MIMEText

        smtp_host = config.get("smtp_host")
        smtp_port = config.get("smtp_port", 587)
        username = config.get("username")
        password = config.get("password")
        from_addr = config.get("from_address")
        to_addrs = config.get("to_addresses", [])

        if not all([smtp_host, username, password, from_addr, to_addrs]):
            logger.warning("Email configuration incomplete")
            return

        msg = MIMEText(message)
        msg["Subject"] = f"Myrm Skill Alert: {metadata.get('skill_id', 'Unknown')}"
        msg["From"] = from_addr
        msg["To"] = ", ".join(to_addrs)

        await asyncio.to_thread(
            self._send_email_sync, smtp_host, smtp_port, username, password, from_addr, to_addrs, msg
        )

        logger.info(f"Alert sent via email to: {', '.join(to_addrs)}")

    def _send_email_sync(
        self, host: str, port: int, username: str, password: str, from_addr: str, to_addrs: list[str], msg: Any
    ) -> None:
        """Synchronous email sending (called in thread)"""
        with smtplib.SMTP(host, port) as server:
            server.starttls()
            server.login(username, password)
            server.sendmail(from_addr, to_addrs, msg.as_string())

    async def _send_webhook(self, config: dict[str, Any], message: str, metadata: dict[str, Any]) -> None:
        """Send alert to custom webhook"""
        import httpx

        url = config.get("url")
        headers = config.get("headers", {})

        if not url:
            logger.warning("Webhook URL not configured")
            return

        payload = {
            "message": message,
            "metadata": metadata,
            "timestamp": datetime.now().isoformat(),
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=payload, headers=headers, timeout=5.0)
            response.raise_for_status()

        logger.info(f"Alert sent to webhook: {url}")

    def _should_send_alert(self, alert_key: str) -> bool:
        """Check rate limit and deduplication"""
        now = datetime.now()

        cutoff_time = now - timedelta(hours=1)
        self._alert_timestamps = [ts for ts in self._alert_timestamps if ts > cutoff_time]

        if len(self._alert_timestamps) >= self.rate_limit_max:
            logger.warning(f"Rate limit exceeded: {len(self._alert_timestamps)} alerts in last hour")
            return False

        if alert_key in self._dedup_cache:
            last_sent = self._dedup_cache[alert_key]
            if now - last_sent < timedelta(minutes=self.dedup_window_minutes):
                return False

        return True

    def _record_alert(self, alert_key: str) -> None:
        """Record alert for rate limiting and deduplication"""
        now = datetime.now()
        self._alert_timestamps.append(now)
        self._dedup_cache[alert_key] = now

        cutoff_time = now - timedelta(minutes=self.dedup_window_minutes * 2)
        self._dedup_cache = {k: v for k, v in self._dedup_cache.items() if v > cutoff_time}

    @staticmethod
    def _generate_dedup_key(skill_id: str, issue_type: str, severity: str) -> str:
        """Generate deduplication key"""
        raw = f"{skill_id}:{issue_type}:{severity}"
        return hashlib.md5(raw.encode()).hexdigest()
