"""Full-spectrum in-process lifecycle interceptor and dynamic context pruning hub.

Coordinates zero-serialization, high-performance in-process event interception across
input gates, dynamic turn preambles, streaming tool inspection, bash environment injection,
context pruning, and compaction overrides.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable

from myrm_agent_harness.runtime.context.full_spectrum_lifecycle_types import (
    InterceptorAction,
    InterceptorDecision,
    LifecycleEventKind,
    LifecycleHubMetrics,
    LifecyclePayload,
)
from myrm_agent_harness.runtime.context.internal_external_message_pipeline_types import (
    AgentMessage,
)

logger = logging.getLogger(__name__)

LifecycleInterceptorCallable = Callable[[LifecyclePayload], InterceptorDecision]


class FullSpectrumLifecycleHub:
    """Central in-process event bus and interceptor orchestrator for runtime lifecycle governance."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._interceptors: dict[
            LifecycleEventKind,
            list[tuple[str, int, LifecycleInterceptorCallable]],
        ] = {kind: [] for kind in LifecycleEventKind}
        self._dispatched_count = 0
        self._blocked_count = 0
        self._modified_count = 0

    def register_interceptor(
        self,
        kind: LifecycleEventKind,
        name: str,
        callback: LifecycleInterceptorCallable,
        priority: int = 100,
    ) -> None:
        """Register an interceptor for a lifecycle event kind; sorted by priority descending."""
        with self._lock:
            # Remove existing registration with same name if present
            self._interceptors[kind] = [
                item for item in self._interceptors[kind] if item[0] != name
            ]
            self._interceptors[kind].append((name, priority, callback))
            self._interceptors[kind].sort(key=lambda item: item[1], reverse=True)
        logger.debug("Registered interceptor '%s' for event '%s' (prio=%d)", name, kind, priority)

    def unregister_interceptor(self, kind: LifecycleEventKind, name: str) -> bool:
        """Unregister an interceptor by name."""
        with self._lock:
            initial_len = len(self._interceptors[kind])
            self._interceptors[kind] = [
                item for item in self._interceptors[kind] if item[0] != name
            ]
            return len(self._interceptors[kind]) < initial_len

    def dispatch(
        self, payload: LifecyclePayload
    ) -> tuple[LifecyclePayload, list[InterceptorDecision]]:
        """Dispatch lifecycle event sequentially across registered interceptors."""
        with self._lock:
            interceptors = list(self._interceptors.get(payload.event_kind, []))
            self._dispatched_count += 1

        current_payload = payload
        decisions: list[InterceptorDecision] = []

        for name, _prio, callback in interceptors:
            try:
                decision = callback(current_payload)
            except Exception as err:
                logger.exception("Error executing lifecycle interceptor '%s': %s", name, err)
                continue

            decisions.append(decision)

            if decision.action == InterceptorAction.BLOCK:
                with self._lock:
                    self._blocked_count += 1
                return current_payload, decisions

            if (
                decision.action in (InterceptorAction.MODIFY, InterceptorAction.REPLACE)
                and decision.modified_payload is not None
            ):
                current_payload = decision.modified_payload
                with self._lock:
                    self._modified_count += 1

        return current_payload, decisions

    def intercept_input(
        self, session_id: str, user_text: str, turn_index: int = 0
    ) -> tuple[str, bool, str | None]:
        """Convenience helper to intercept, sanitize, or block incoming user text before inference."""
        payload = LifecyclePayload(
            event_kind=LifecycleEventKind.INPUT,
            session_id=session_id,
            turn_index=turn_index,
            text=user_text,
        )
        final_payload, decisions = self.dispatch(payload)
        for d in decisions:
            if d.action == InterceptorAction.BLOCK:
                return final_payload.text or user_text, True, d.block_reason
        return final_payload.text or user_text, False, None

    def intercept_before_turn(
        self,
        session_id: str,
        system_prompt: str,
        messages: list[AgentMessage],
        turn_index: int = 0,
    ) -> tuple[str, list[AgentMessage]]:
        """Allow plugins to dynamically mutate system prompt or inject turns before LLM initiation."""
        payload = LifecyclePayload(
            event_kind=LifecycleEventKind.BEFORE_TURN_START,
            session_id=session_id,
            turn_index=turn_index,
            text=system_prompt,
            context_messages=messages,
        )
        final_payload, _ = self.dispatch(payload)
        return (
            final_payload.text or system_prompt,
            final_payload.context_messages or messages,
        )

    def intercept_bash_spawn(
        self,
        session_id: str,
        command: str,
        env_vars: dict[str, str],
        turn_index: int = 0,
    ) -> tuple[str, dict[str, str], bool, str | None]:
        """Allow security and container hooks to audit/mutate commands and inject environment variables."""
        payload = LifecyclePayload(
            event_kind=LifecycleEventKind.BASH_SPAWN_HOOK,
            session_id=session_id,
            turn_index=turn_index,
            text=command,
            env_vars=env_vars,
        )
        final_payload, decisions = self.dispatch(payload)
        for d in decisions:
            if d.action == InterceptorAction.BLOCK:
                return (
                    final_payload.text or command,
                    final_payload.env_vars or env_vars,
                    True,
                    d.block_reason,
                )
        return (
            final_payload.text or command,
            final_payload.env_vars or env_vars,
            False,
            None,
        )

    def intercept_dynamic_context_prune(
        self,
        session_id: str,
        messages: list[AgentMessage],
        turn_index: int = 0,
    ) -> list[AgentMessage]:
        """Allow deep-inspection plugins to prune noisy or obsolete messages from the context window."""
        payload = LifecyclePayload(
            event_kind=LifecycleEventKind.CONTEXT_DYNAMIC_PRUNE,
            session_id=session_id,
            turn_index=turn_index,
            context_messages=messages,
        )
        final_payload, _ = self.dispatch(payload)
        return final_payload.context_messages or messages

    def intercept_before_compact(
        self,
        session_id: str,
        messages: list[AgentMessage],
        turn_index: int = 0,
    ) -> tuple[bool, list[AgentMessage] | None]:
        """Allow external extensions to completely replace or enhance the compaction algorithm."""
        payload = LifecyclePayload(
            event_kind=LifecycleEventKind.SESSION_BEFORE_COMPACT,
            session_id=session_id,
            turn_index=turn_index,
            context_messages=messages,
        )
        final_payload, decisions = self.dispatch(payload)
        for d in decisions:
            if d.action == InterceptorAction.REPLACE and final_payload.context_messages is not None:
                return True, final_payload.context_messages
        return False, None

    def get_metrics(self) -> LifecycleHubMetrics:
        """Return execution metrics across all intercepted events."""
        with self._lock:
            total_registered = sum(len(items) for items in self._interceptors.values())
            return LifecycleHubMetrics(
                dispatched_events_count=self._dispatched_count,
                blocked_events_count=self._blocked_count,
                modified_events_count=self._modified_count,
                registered_interceptors_count=total_registered,
            )
