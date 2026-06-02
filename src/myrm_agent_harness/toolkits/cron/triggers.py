"""Trigger type definitions and security helpers.

Provides data models for 6 trigger kinds (cron, event, system_event,
webhook, poll, manual), ``TriggerConfig`` (container for per-job trigger
rules), and security utilities (SSRF protection, ReDoS prevention,
constant-time HMAC comparison).

Concrete trigger matching and dispatching is implemented by the application
layer via the ``TriggerProvider`` protocol in ``protocols.py``.

[INPUT]
- (none)

[OUTPUT]
- TriggerKind: Fires when an incoming message matches a regex pattern.
- EventTrigger: class — Event Trigger
- SystemEventTrigger: Fires on structured system events (e.g. GitHub webhook pa...
- WebhookTrigger: Fires when an HTTP request hits the job's webhook endpoint.
- PollTrigger: Periodically fetches a URL and fires when the content cha...

[POS]
Trigger type definitions and security helpers.
"""

from __future__ import annotations

import hmac
import ipaddress
import os
import re
import socket
from dataclasses import dataclass, field
from enum import StrEnum
from urllib.parse import urlparse


class TriggerKind(StrEnum):
    CRON = "cron"
    EVENT = "event"
    SYSTEM_EVENT = "system"
    WEBHOOK = "webhook"
    POLL = "poll"
    MANUAL = "manual"


# ---------------------------------------------------------------------------
# Trigger data models
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class EventTrigger:
    """Fires when an incoming message matches a regex pattern.

    ``max_pattern_bytes`` caps the compiled regex size to prevent ReDoS.
    """

    pattern: str
    channel: str | None = None
    max_pattern_bytes: int = 65_536


@dataclass(frozen=True, slots=True)
class SystemEventTrigger:
    """Fires on structured system events (e.g. GitHub webhook payloads).

    ``filters`` is a dict of payload field → expected value for exact matching.
    """

    source: str
    event_type: str
    filters: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class WebhookTrigger:
    """Fires when an HTTP request hits the job's webhook endpoint.

    ``path`` defaults to the job ID if not set.
    ``secret`` is used for HMAC-SHA256 signature verification.
    """

    path: str | None = None
    secret: str | None = None


@dataclass(frozen=True, slots=True)
class PollTrigger:
    """Periodically fetches a URL and fires when the content changes.

    ``json_path`` optionally extracts a sub-field from JSON responses.
    ``change_detection`` enables content-hash comparison between polls.
    """

    url: str
    json_path: str | None = None
    interval_seconds: int = 300
    change_detection: bool = True


# ---------------------------------------------------------------------------
# TriggerConfig — per-job trigger rules container
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TriggerConfig:
    """Per-job trigger rules.  Multiple triggers of the same or different
    kinds can be attached.  Any single match fires the job.

    Uses tuples (not lists) for immutability — consistent with ``CronJob``'s
    other collection fields (``required_capabilities``, ``allowed_roots``).
    """

    webhooks: tuple[WebhookTrigger, ...] = ()
    events: tuple[EventTrigger, ...] = ()
    system_events: tuple[SystemEventTrigger, ...] = ()


# ---------------------------------------------------------------------------
# TriggerConfig serialization
# ---------------------------------------------------------------------------


def trigger_config_to_dict(tc: TriggerConfig | None) -> dict[str, list[dict[str, object]]] | None:
    """Serialise ``TriggerConfig`` to a JSON-safe dict, or None."""
    if tc is None:
        return None
    d: dict[str, list[dict[str, object]]] = {}
    if tc.webhooks:
        d["webhooks"] = [{"path": w.path, "secret": w.secret} for w in tc.webhooks]
    if tc.events:
        d["events"] = [
            {"pattern": e.pattern, "channel": e.channel, "max_pattern_bytes": e.max_pattern_bytes} for e in tc.events
        ]
    if tc.system_events:
        d["system_events"] = [
            {"source": s.source, "event_type": s.event_type, "filters": s.filters} for s in tc.system_events
        ]
    return d if d else None


def dict_to_trigger_config(d: dict[str, list[dict[str, object]]] | None) -> TriggerConfig | None:
    """Convert a JSON dict to ``TriggerConfig``, or None if missing/empty."""
    if not d:
        return None

    webhooks = tuple(
        WebhookTrigger(
            path=str(w.get("path", "")),
            secret=str(w.get("secret", "")) if w.get("secret") else None,
        )
        for w in d.get("webhooks", [])
    )
    events = tuple(
        EventTrigger(
            pattern=str(e["pattern"]),
            channel=str(e["channel"]) if e.get("channel") else None,
            max_pattern_bytes=int(e.get("max_pattern_bytes", 65_536)),  # type: ignore[arg-type]
        )
        for e in d.get("events", [])
    )
    system_events = tuple(
        SystemEventTrigger(
            source=str(s["source"]),
            event_type=str(s["event_type"]),
            filters=dict(s.get("filters", {})),  # type: ignore[arg-type]
        )
        for s in d.get("system_events", [])
    )

    tc = TriggerConfig(webhooks=webhooks, events=events, system_events=system_events)
    if not tc.webhooks and not tc.events and not tc.system_events:
        return None
    return tc


# ---------------------------------------------------------------------------
# Webhook path / secret generation
# ---------------------------------------------------------------------------

_WEBHOOK_PATH_LENGTH = 16
_WEBHOOK_SECRET_LENGTH = 32


def generate_webhook_path() -> str:
    """Generate a URL-safe random webhook path (hex-encoded)."""
    return os.urandom(_WEBHOOK_PATH_LENGTH).hex()


def generate_webhook_secret() -> str:
    """Generate a cryptographically secure webhook secret (hex-encoded)."""
    return os.urandom(_WEBHOOK_SECRET_LENGTH).hex()


# ---------------------------------------------------------------------------
# Security utilities
# ---------------------------------------------------------------------------

_PRIVATE_HOSTNAMES = frozenset({"localhost", "127.0.0.1", "::1", "0.0.0.0"})


def validate_webhook_secret(expected: str, provided: str) -> bool:
    """Constant-time comparison of webhook secrets to prevent timing attacks."""
    return hmac.compare_digest(expected.encode(), provided.encode())


def is_private_url(url: str) -> bool:
    """SSRF protection: return True if *url* resolves to a private/internal address.

    Performs DNS resolution to catch DNS-rebinding attacks where a public
    hostname resolves to a private IP.
    """
    parsed = urlparse(url)
    hostname = parsed.hostname
    if not hostname:
        return True
    if hostname in _PRIVATE_HOSTNAMES:
        return True
    try:
        for info in socket.getaddrinfo(hostname, None):
            ip = ipaddress.ip_address(info[4][0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                return True
    except (socket.gaierror, ValueError):
        return True
    return False


def validate_regex_pattern(pattern: str, *, max_bytes: int = 65_536) -> re.Pattern[str]:
    """Compile a regex with a size limit to prevent ReDoS attacks.

    Raises ``ValueError`` if the pattern source exceeds *max_bytes*.
    """
    encoded_len = len(pattern.encode())
    if encoded_len > max_bytes:
        raise ValueError(f"Regex pattern too large: {encoded_len} > {max_bytes} bytes")
    return re.compile(pattern)
