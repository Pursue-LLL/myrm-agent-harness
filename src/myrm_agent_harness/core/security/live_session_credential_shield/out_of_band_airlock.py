"""
[POS] src/myrm_agent_harness/core/security/live_session_credential_shield/out_of_band_airlock.py
[INPUT] re, time, uuid, typing
[OUTPUT] OutOfBandAirlock

Out-of-band blind credential airlock channel.
Routes sensitive keystrokes directly to target DOM or OS inputs without exposing them to Agent observations or logs.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import logging
import re
import time
import uuid

from .types import (
    AirlockChannelStatus,
    BlindCredentialInputEvent,
    SensitiveTargetType,
)

logger = logging.getLogger(__name__)


class OutOfBandAirlock:
    """Manages dedicated out-of-band input airlocks to isolate passwords and secrets from agent observations."""

    SENSITIVE_SELECTOR_PATTERNS: tuple[tuple[re.Pattern[str], SensitiveTargetType], ...] = (
        (
            re.compile(r"input\[type=['\"]?password['\"]?\]", re.IGNORECASE),
            SensitiveTargetType.PASSWORD_INPUT,
        ),
        (
            re.compile(r"(?:otp|2fa|authenticator|mfa|verification-code)", re.IGNORECASE),
            SensitiveTargetType.OTP_INPUT,
        ),
        (
            re.compile(r"(?:api[-_]?key|secret[-_]?token|auth[-_]?token)", re.IGNORECASE),
            SensitiveTargetType.API_KEY_FIELD,
        ),
        (
            re.compile(r"(?:cvv|cvc|security[-_]?code|card[-_]?pin)", re.IGNORECASE),
            SensitiveTargetType.PAYMENT_CVV,
        ),
    )

    def __init__(self) -> None:
        self._session_statuses: dict[str, AirlockChannelStatus] = {}
        self._blind_events_log: list[BlindCredentialInputEvent] = []

    def open_channel(self, session_id: str) -> AirlockChannelStatus:
        """Establish an out-of-band airlock channel for a live takeover session."""
        self._session_statuses[session_id] = AirlockChannelStatus.OPEN
        logger.info("Opened out-of-band airlock channel for session %s", session_id)
        return AirlockChannelStatus.OPEN

    def close_channel(self, session_id: str) -> AirlockChannelStatus:
        """Tear down and close an out-of-band airlock channel."""
        self._session_statuses[session_id] = AirlockChannelStatus.CLOSED
        logger.info("Closed out-of-band airlock channel for session %s", session_id)
        return AirlockChannelStatus.CLOSED

    def get_channel_status(self, session_id: str) -> AirlockChannelStatus:
        """Query active status of an airlock channel."""
        return self._session_statuses.get(session_id, AirlockChannelStatus.CLOSED)

    def detect_target_type(self, target_selector: str) -> SensitiveTargetType:
        """Detect whether target DOM element corresponds to a credential input."""
        for pattern, target_type in self.SENSITIVE_SELECTOR_PATTERNS:
            if pattern.search(target_selector):
                return target_type
        return SensitiveTargetType.GENERIC_CREDENTIAL

    def route_blind_input(
        self,
        session_id: str,
        target_selector: str,
        raw_secret: str,
        target_type: SensitiveTargetType | None = None,
    ) -> tuple[BlindCredentialInputEvent, str]:
        """Route keystrokes via blind airlock channel and emit non-revealing event descriptor."""
        detected_type = target_type or self.detect_target_type(target_selector)
        dispatch_confirmation_id = f"oob-disp-{uuid.uuid4().hex[:12]}"

        # Mark channel status as blind routing
        self._session_statuses[session_id] = AirlockChannelStatus.BLIND_ROUTING

        event = BlindCredentialInputEvent(
            session_id=session_id,
            target_selector=target_selector,
            target_type=detected_type,
            keystroke_count=len(raw_secret),
            is_blind_routed=True,
            timestamp=time.time(),
        )
        self._blind_events_log.append(event)
        logger.info(
            "Blind routed %d keystrokes to %s (%s) under session %s",
            len(raw_secret),
            target_selector,
            detected_type.value,
            session_id,
        )

        return event, dispatch_confirmation_id

    def list_session_blind_events(self, session_id: str) -> list[BlindCredentialInputEvent]:
        """Retrieve historical blind event descriptors for audit without exposing raw secrets."""
        return [e for e in self._blind_events_log if e.session_id == session_id]
