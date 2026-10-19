"""Per-run state and per-turn disclosure registry for the completion guard.

Two concerns live here, both scoped to a single assistant turn:

1. **Guard state** — the rejection budget and forced-finish latch. Scoping the
   budget per turn keeps concurrent runs (multi-session streams, background
   reruns and cron jobs inside one server process) independent: one turn can
   neither reset nor exhaust another turn's budget. Entries are keyed by the
   bound message id the runtime stamps for the turn, with a small
   insertion-order LRU cap so long-lived processes stay flat.
2. **Disclosure payload** — the evidence tier badge and the auto-staged
   deliverable drafts the post-run event emitter reads once for ``message_end``.
   The server persists them as message metadata so the UI can show what a
   delivery is backed by.

The tier publisher applies the disclosure policy from
``deliverable_confidence_tier``: evidence-bearing tiers always go out, the PLAN
tier only when the user asked for work (casual conversation stays clean).
"""

from __future__ import annotations

from dataclasses import dataclass

from myrm_agent_harness.agent.middlewares.completion.deliverable_confidence_tier import (
    resolve_deliverable_tier,
    should_disclose_tier,
)
from myrm_agent_harness.agent.security.guards.loop_guard import CallRecord

RUN_STATE_LIMIT = 128
UNBOUND_RUN_KEY = ""


@dataclass(slots=True)
class RunGuardState:
    """Rejection budget and forced-finish latch for one assistant turn."""

    rejections: int = 0
    forced_finish: bool = False


_run_states: dict[str, RunGuardState] = {}
_run_disclosures: dict[str, dict[str, object]] = {}


def run_key() -> str:
    """Identify the current assistant turn (message id set by the runtime)."""
    from myrm_agent_harness.agent.meta_tools.file_ops.observers.snapshot_observer import (
        get_bound_message_id,
    )

    return get_bound_message_id() or UNBOUND_RUN_KEY


def current_run_state() -> RunGuardState:
    """Return this turn's guard state, creating it on first use."""
    key = run_key()
    state = _run_states.get(key)
    if state is None:
        state = RunGuardState()
        _run_states[key] = state
        _trim_registry(_run_states)
    return state


def reset_run_state() -> None:
    """Drop this turn's guard state and disclosure payload."""
    key = run_key()
    _run_states.pop(key, None)
    _run_disclosures.pop(key, None)


def _trim_registry(registry: dict[str, object]) -> None:
    while len(registry) > RUN_STATE_LIMIT:
        registry.pop(next(iter(registry)), None)


def publish_disclosure(
    *,
    deliverable_tier: dict[str, object] | None = None,
    staged_artifacts: list[dict[str, object]] | None = None,
) -> None:
    """Record what the UI may disclose for this turn (latest values win)."""
    entry = _run_disclosures.setdefault(run_key(), {})
    if deliverable_tier is not None:
        entry["deliverable_tier"] = deliverable_tier
    if staged_artifacts:
        entry["staged_artifacts"] = staged_artifacts
    _trim_registry(_run_disclosures)


def pop_run_disclosure(message_id: str) -> dict[str, object] | None:
    """Return and clear the disclosure payload for a completed turn."""
    return _run_disclosures.pop(message_id or UNBOUND_RUN_KEY, None)


def publish_tier_disclosure(
    content: str,
    records: list[CallRecord],
    user_text: str | None,
) -> None:
    """Publish the evidence tier the UI may show for this turn."""
    if not content.strip():
        return
    metadata = resolve_deliverable_tier(records, content=content)
    if not should_disclose_tier(metadata, user_text=user_text):
        return
    publish_disclosure(deliverable_tier=metadata.to_dict())


def attach_disclosure_to_event(event: dict[str, object], message_id: str) -> None:
    """Attach the turn's disclosure payload (if any) to a ``message_end`` event."""
    disclosure = pop_run_disclosure(message_id)
    if not disclosure:
        return
    deliverable_tier = disclosure.get("deliverable_tier")
    if isinstance(deliverable_tier, dict):
        event["deliverable_tier"] = deliverable_tier
    staged_artifacts = disclosure.get("staged_artifacts")
    if isinstance(staged_artifacts, list) and staged_artifacts:
        event["staged_artifacts"] = staged_artifacts


__all__ = [
    "RUN_STATE_LIMIT",
    "UNBOUND_RUN_KEY",
    "RunGuardState",
    "attach_disclosure_to_event",
    "current_run_state",
    "pop_run_disclosure",
    "publish_disclosure",
    "publish_tier_disclosure",
    "reset_run_state",
    "run_key",
]
