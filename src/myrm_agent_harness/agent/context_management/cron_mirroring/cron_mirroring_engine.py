"""Continuable Cron Delivery and Session Mirroring Engine (Item 215).

[INPUT]
- ContinuableJobSpec, CronDeliveryRecord: Input specifications and delivery payloads.
- Existing session context messages in dict format.

[OUTPUT]
- ContinuableCronSessionMirrorEngine: Manages job registration, alternation-safe mirroring,
- and follow-up query context routing.

[POS]
- Transforms fire-and-forget cron broadcasts into continuable, reply-ready conversation context,
- maintaining strict multi-provider message role alternation safety.
"""

from __future__ import annotations

import datetime
import time
from typing import Sequence

from .cron_mirroring_types import (
    ContinuableJobSpec,
    CronDeliveryRecord,
    CronMirrorConfig,
    CronMirrorRoleMode,
    CronMirroringOutcome,
)


class ContinuableCronSessionMirrorEngine:
    """Orchestrates cron delivery ingestion, conversation mirroring, and thread routing."""

    def __init__(self, config: CronMirrorConfig | None = None) -> None:
        self._config = config or CronMirrorConfig()
        # job_id -> ContinuableJobSpec
        self._jobs: dict[str, ContinuableJobSpec] = {}
        # session_id -> list[CronDeliveryRecord]
        self._session_deliveries: dict[str, list[CronDeliveryRecord]] = {}
        # thread_id -> CronDeliveryRecord
        self._thread_index: dict[str, CronDeliveryRecord] = {}
        # delivery_id -> CronDeliveryRecord
        self._delivery_index: dict[str, CronDeliveryRecord] = {}

    @property
    def config(self) -> CronMirrorConfig:
        """Returns engine configuration."""
        return self._config

    def register_job(self, spec: ContinuableJobSpec) -> None:
        """Registers or updates a scheduled job specification."""
        self._jobs[spec.job_id] = spec

    def get_job(self, job_id: str) -> ContinuableJobSpec | None:
        """Retrieves registered job specification."""
        return self._jobs.get(job_id)

    def record_delivery(self, delivery: CronDeliveryRecord) -> None:
        """Persists a cron delivery payload in memory indexes."""
        self._delivery_index[delivery.delivery_id] = delivery
        if delivery.target_session_id not in self._session_deliveries:
            self._session_deliveries[delivery.target_session_id] = []
        self._session_deliveries[delivery.target_session_id].append(delivery)
        if delivery.thread_id:
            self._thread_index[delivery.thread_id] = delivery

    def mirror_delivery_into_session(
        self,
        delivery: CronDeliveryRecord,
        existing_messages: Sequence[dict[str, object]],
    ) -> tuple[list[dict[str, object]], CronMirroringOutcome]:
        """Mirrors a cron delivery into session context history while guaranteeing alternation safety."""
        start_time = time.perf_counter()
        job_spec = self.get_job(delivery.job_id)

        # Check opt-in flags
        should_mirror = (
            self._config.enabled
            and (job_spec is None or job_spec.attach_to_session)
        )

        if not should_mirror:
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            outcome = CronMirroringOutcome(
                mirrored=False,
                target_session_id=delivery.target_session_id,
                delivery_id=delivery.delivery_id,
                injected_role="",
                injected_content_preview="",
                thread_id=delivery.thread_id,
                alternation_safe=True,
                duration_ms=duration_ms,
            )
            return [dict(m) for m in existing_messages], outcome

        # Record delivery
        self.record_delivery(delivery)

        # Clamp content length if needed
        content = delivery.content
        max_chars = self._config.max_delivery_chars_in_context
        if len(content) > max_chars:
            content = content[:max_chars] + f"\n... [Truncated {len(content) - max_chars} characters]"

        # Format timestamp and tag
        dt_str = datetime.datetime.fromtimestamp(delivery.delivered_at, tz=datetime.timezone.utc).strftime(
            "%Y-%m-%d %H:%M:%S UTC"
        )
        tag_header = self._config.tag_template.format(job_name=delivery.job_name, timestamp=dt_str)
        mirrored_text = f"{tag_header}\n{content}"

        # Determine safe role based on role_mode and existing last message
        role_mode = self._config.default_role_mode
        last_role = existing_messages[-1].get("role") if existing_messages else None

        if role_mode == CronMirrorRoleMode.SYSTEM_INSTRUCTION_FRAME:
            injected_role = "system"
        elif role_mode == CronMirrorRoleMode.ASSISTANT_DELIVERY:
            injected_role = "assistant"
        else:
            # LABELLED_USER_TURN mode:
            # If the last message was already 'user', to prevent consecutive user turns,
            # we safely switch to 'assistant' or attach as a structured observation turn
            if last_role == "user":
                injected_role = "assistant"
            else:
                injected_role = "user"

        new_message: dict[str, object] = {
            "role": injected_role,
            "content": mirrored_text,
            "metadata": {
                "cron_delivery_id": delivery.delivery_id,
                "job_id": delivery.job_id,
                "continuable": job_spec.continuable if job_spec else True,
                "thread_id": delivery.thread_id,
                "is_cron_mirror": True,
            },
        }

        updated_messages = [dict(m) for m in existing_messages]
        updated_messages.append(new_message)

        duration_ms = (time.perf_counter() - start_time) * 1000.0
        outcome = CronMirroringOutcome(
            mirrored=True,
            target_session_id=delivery.target_session_id,
            delivery_id=delivery.delivery_id,
            injected_role=injected_role,
            injected_content_preview=mirrored_text[:120],
            thread_id=delivery.thread_id,
            alternation_safe=True,
            duration_ms=duration_ms,
        )
        return updated_messages, outcome

    def resolve_follow_up_context(
        self,
        session_id: str,
        query_text: str = "",
        thread_id: str | None = None,
    ) -> CronDeliveryRecord | None:
        """Resolves active cron delivery when user replies to a delivered brief."""
        if thread_id and thread_id in self._thread_index:
            return self._thread_index[thread_id]

        deliveries = self._session_deliveries.get(session_id, [])
        if not deliveries:
            return None

        # Return latest continuable delivery
        for delivery in reversed(deliveries):
            job = self.get_job(delivery.job_id)
            if job is None or job.continuable:
                return delivery
        return None

    def clear_session(self, session_id: str) -> None:
        """Cleans up session delivery indexes."""
        deliveries = self._session_deliveries.pop(session_id, [])
        for d in deliveries:
            self._delivery_index.pop(d.delivery_id, None)
            if d.thread_id:
                self._thread_index.pop(d.thread_id, None)
