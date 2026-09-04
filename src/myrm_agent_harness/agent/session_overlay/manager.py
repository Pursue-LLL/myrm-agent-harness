"""Session overlay manager with single-shot trial and rollback guard.

[INPUT]
- contextvars, threading (POS: Python standard library)
- .schema::(OverlayScope, OverlayStatus, OverlayTargetType, SessionOverlay)

[OUTPUT]
- SessionOverlayManager: In-memory session lifecycle and rollback controller
- get_session_overlay_manager(): ContextVar accessor
- reset_session_overlay_manager(): Session cleanup hook

[POS]
Maintains active session overlays, applies argument-stripping adapters,
enforces single-shot trial rollback guard, and decrements TTL per turn.
"""

from __future__ import annotations

import threading
from contextvars import ContextVar

from myrm_agent_harness.agent.session_overlay.schema import (
    OverlayScope,
    OverlayStatus,
    OverlayTargetType,
    SessionOverlay,
)
from myrm_agent_harness.utils.logger_utils import get_agent_logger

logger = get_agent_logger(__name__)

MAX_ACTIVE_OVERLAYS = 2


class SessionOverlayManager:
    """Manages active session overlays, parameter adaptations, and rollbacks."""

    def __init__(self, session_id: str = "default") -> None:
        self.session_id = session_id
        self._overlays: dict[str, SessionOverlay] = {}
        self._successful_overlays: list[SessionOverlay] = []
        self.total_rollbacks: int = 0
        self._lock = threading.Lock()

    def register_overlay(self, overlay: SessionOverlay) -> bool:
        """Register a new session overlay. Enforces MAX_ACTIVE_OVERLAYS cap and deduplicates targets."""
        with self._lock:
            existing_target_id = next(
                (
                    k
                    for k, v in self._overlays.items()
                    if v.is_alive()
                    and v.target_type == overlay.target_type
                    and v.target_name == overlay.target_name
                    and v.target_name != "global"
                ),
                None,
            )
            if existing_target_id is not None:
                old_ovl = self._overlays[existing_target_id]
                self._overlays[existing_target_id] = SessionOverlay(
                    overlay_id=old_ovl.overlay_id,
                    scope=overlay.scope,
                    target_type=overlay.target_type,
                    target_name=overlay.target_name,
                    patch_payload={**old_ovl.patch_payload, **overlay.patch_payload},
                    ttl_turns=max(old_ovl.ttl_turns, overlay.ttl_turns),
                    attempt_count=old_ovl.attempt_count + 1,
                    failure_signature=overlay.failure_signature or old_ovl.failure_signature,
                    status=OverlayStatus.ACTIVE,
                )
                logger.info(
                    "[SessionOverlay] Refreshed existing overlay %s on '%s' (TTL=%d)",
                    old_ovl.overlay_id,
                    old_ovl.target_name,
                    self._overlays[existing_target_id].ttl_turns,
                )
                return True

            active_count = sum(1 for o in self._overlays.values() if o.is_alive())
            if active_count >= MAX_ACTIVE_OVERLAYS:
                # Evict earliest active overlay to prevent cascade
                earliest = next((k for k, v in self._overlays.items() if v.is_alive()), None)
                if earliest:
                    self._overlays[earliest] = SessionOverlay(
                        overlay_id=self._overlays[earliest].overlay_id,
                        scope=self._overlays[earliest].scope,
                        target_type=self._overlays[earliest].target_type,
                        target_name=self._overlays[earliest].target_name,
                        patch_payload=self._overlays[earliest].patch_payload,
                        ttl_turns=0,
                        status=OverlayStatus.EXPIRED,
                    )

            self._overlays[overlay.overlay_id] = overlay
            logger.info(
                "[SessionOverlay] Registered %s (%s on '%s', TTL=%d)",
                overlay.overlay_id,
                overlay.target_type.value,
                overlay.target_name,
                overlay.ttl_turns,
            )
            return True

    def apply_overlay(self, overlay: SessionOverlay) -> bool:
        """Alias for register_overlay."""
        return self.register_overlay(overlay)

    def get_active_overlays(
        self,
        scope: OverlayScope | None = None,
        target_type: OverlayTargetType | None = None,
        target_name: str | None = None,
    ) -> list[SessionOverlay]:
        """Query currently active overlays matching optional criteria."""
        with self._lock:
            results: list[SessionOverlay] = []
            for ovl in self._overlays.values():
                if not ovl.is_alive():
                    continue
                if scope is not None and ovl.scope != scope:
                    continue
                if target_type is not None and ovl.target_type != target_type:
                    continue
                if target_name is not None and ovl.target_name != target_name and ovl.target_name != "global":
                    continue
                results.append(ovl)
            return results

    def apply_tool_args_adaptation(
        self, tool_name: str, tool_args: dict[str, object]
    ) -> tuple[dict[str, object], SessionOverlay | None]:
        """Apply active argument-stripping or alias patch if target tool matches."""
        active = self.get_active_overlays(
            target_type=OverlayTargetType.TEMP_SKILL_VARIANT, target_name=tool_name
        )
        if not active:
            return tool_args, None

        selected = active[0]
        strip_params = selected.patch_payload.get("strip_params")
        if not isinstance(strip_params, list):
            return tool_args, selected

        adapted_args = {k: v for k, v in tool_args.items() if k not in strip_params}
        logger.info(
            "[SessionOverlay] Applied strip_params %s on '%s' via %s",
            strip_params,
            tool_name,
            selected.overlay_id,
        )
        return adapted_args, selected

    def record_tool_outcome(
        self, tool_name: str, is_error: bool, error_signature: str = ""
    ) -> list[str]:
        """Record tool execution outcome. Triggers Trial & Rollback Guard on failure."""
        rolled_back_ids: list[str] = []
        with self._lock:
            for ovl_id, ovl in list(self._overlays.items()):
                if not ovl.is_alive() or ovl.target_name != tool_name:
                    continue

                if is_error:
                    # Trial failed under this overlay: execute physical rollback
                    self.total_rollbacks += 1
                    logger.warning(
                        "[SessionOverlay] Trial failed for %s on '%s'. Rolling back to prevent patch cascade.",
                        ovl_id,
                        tool_name,
                    )
                    self._overlays[ovl_id] = SessionOverlay(
                        overlay_id=ovl.overlay_id,
                        scope=ovl.scope,
                        target_type=ovl.target_type,
                        target_name=ovl.target_name,
                        patch_payload=ovl.patch_payload,
                        ttl_turns=0,
                        attempt_count=ovl.attempt_count + 1,
                        failure_signature=error_signature or ovl.failure_signature,
                        status=OverlayStatus.ROLLED_BACK,
                    )
                    rolled_back_ids.append(ovl_id)
                else:
                    # Success: increment attempt, decrement TTL per tool invocation cycle, and record for Growth
                    new_ttl = max(0, ovl.ttl_turns - 1)
                    new_status = OverlayStatus.ACTIVE if new_ttl > 0 else OverlayStatus.EXPIRED
                    self._overlays[ovl_id] = SessionOverlay(
                        overlay_id=ovl.overlay_id,
                        scope=ovl.scope,
                        target_type=ovl.target_type,
                        target_name=ovl.target_name,
                        patch_payload=ovl.patch_payload,
                        ttl_turns=new_ttl,
                        attempt_count=ovl.attempt_count + 1,
                        failure_signature=ovl.failure_signature,
                        status=new_status,
                    )
                    if ovl not in self._successful_overlays:
                        self._successful_overlays.append(ovl)

        return rolled_back_ids

    def rollback_overlay(self, overlay_id: str) -> bool:
        """Manually rollback an active overlay by its ID (HITL/API entrypoint)."""
        with self._lock:
            ovl = self._overlays.get(overlay_id)
            if ovl is None or not ovl.is_alive():
                return False
            self._overlays[overlay_id] = SessionOverlay(
                overlay_id=ovl.overlay_id,
                scope=ovl.scope,
                target_type=ovl.target_type,
                target_name=ovl.target_name,
                patch_payload=ovl.patch_payload,
                ttl_turns=0,
                attempt_count=ovl.attempt_count,
                failure_signature=ovl.failure_signature,
                status=OverlayStatus.ROLLED_BACK,
            )
            logger.info("[SessionOverlay] Manually rolled back overlay %s", overlay_id)
            return True

    def consume_turn(self) -> list[str]:
        """Decrement TTL for active overlays at turn boundary. Auto-expire zero-TTL overlays."""
        expired_ids: list[str] = []
        with self._lock:
            for ovl_id, ovl in list(self._overlays.items()):
                if not ovl.is_alive():
                    continue
                new_ttl = ovl.ttl_turns - 1
                new_status = OverlayStatus.ACTIVE if new_ttl > 0 else OverlayStatus.EXPIRED
                self._overlays[ovl_id] = SessionOverlay(
                    overlay_id=ovl.overlay_id,
                    scope=ovl.scope,
                    target_type=ovl.target_type,
                    target_name=ovl.target_name,
                    patch_payload=ovl.patch_payload,
                    ttl_turns=max(0, new_ttl),
                    attempt_count=ovl.attempt_count,
                    failure_signature=ovl.failure_signature,
                    status=new_status,
                )
                if new_status == OverlayStatus.EXPIRED:
                    expired_ids.append(ovl_id)
                    logger.info("[SessionOverlay] %s expired gracefully (TTL=0)", ovl_id)
        return expired_ids

    def get_active_negative_constraints(self) -> list[str]:
        """Retrieve active negative pattern constraints for turn prompt injection."""
        overlays = self.get_active_overlays(target_type=OverlayTargetType.PROCEDURAL_MEMORY)
        constraints: list[str] = []
        for ovl in overlays:
            c = ovl.patch_payload.get("negative_constraint")
            if isinstance(c, str) and c:
                constraints.append(c)
        return constraints

    def get_advisories(self) -> list[str]:
        """Retrieve all active advisory instructions across active overlays."""
        with self._lock:
            advisories: list[str] = []
            for ovl in self._overlays.values():
                if not ovl.is_alive():
                    continue
                adv = ovl.patch_payload.get("advisory_instruction") or ovl.patch_payload.get("negative_constraint")
                if isinstance(adv, str) and adv:
                    advisories.append(adv)
            return advisories

    def tick(self, current_turn: int | None = None) -> list[str]:
        """Alias for consume_turn for turn boundary lifecycle ticking."""
        return self.consume_turn()

    def export_growth_manifests(self) -> list[dict[str, object]]:
        """Export successfully verified overlays for post-run Growth review."""
        with self._lock:
            return [ovl.to_dict() for ovl in self._successful_overlays]


# ---------------------------------------------------------------------------
# ContextVar session bindings
# ---------------------------------------------------------------------------

_overlay_manager_var: ContextVar[SessionOverlayManager | None] = ContextVar(
    "session_overlay_manager", default=None
)


def get_session_overlay_manager(session_id: str = "default") -> SessionOverlayManager:
    """Retrieve or create the session-bound overlay manager."""
    mgr = _overlay_manager_var.get()
    if mgr is None or mgr.session_id != session_id:
        mgr = SessionOverlayManager(session_id=session_id)
        _overlay_manager_var.set(mgr)
    return mgr


def reset_session_overlay_manager() -> None:
    """Clear the active session overlay manager from context."""
    _overlay_manager_var.set(None)
