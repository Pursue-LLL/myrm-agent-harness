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
tier only when the answer itself makes a completion claim (casual conversation
and inline deliverables stay clean).

[INPUT]
- agent.middlewares.completion.deliverable_confidence_tier::resolve_deliverable_tier, should_disclose_tier (POS: 交付置信档解析与披露策略)
- agent.meta_tools.file_ops.observers.snapshot_observer::get_bound_message_id (POS: 本轮 assistant 消息 id)
- agent.security.guards.loop_guard::CallRecord (POS: 工具调用记录)

[OUTPUT]
- current_run_state / reset_run_state: 当前回合的拦截预算与强制收尾闩锁
- publish_disclosure / pop_run_disclosure / publish_tier_disclosure: 每轮披露载荷的写入与取用
- attach_disclosure_to_event(): 把披露载荷挂到 message_end 事件

[POS]
完成门禁的回合级状态与披露登记处。状态按 runtime 绑定的消息 id 分桶（LRU 128），并发回合互不影响；披露载荷供 post-run 事件一次性消费。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from myrm_agent_harness.agent.middlewares.completion.deliverable_confidence_tier import (
    resolve_deliverable_tier,
    should_disclose_tier,
)
from myrm_agent_harness.agent.security.guards.loop_guard import CallRecord

RUN_STATE_LIMIT = 128
UNBOUND_RUN_KEY = ""


@dataclass(slots=True)
class RunGuardState:
    """Rejection budget, forced-finish latch and evidence ledger for one turn.

    A turn can run in several segments (HITL resume, retry, continuation). The
    disclosure must describe what the *turn* produced, so the evidence recorded
    by earlier segments stays here while the guard's own checks keep reading the
    current segment's window.
    """

    rejections: int = 0
    forced_finish: bool = False
    evidence: list[CallRecord] = field(default_factory=list)


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


def record_evidence(records: list[CallRecord]) -> list[CallRecord]:
    """Merge the current segment's records into the turn ledger (idempotent)."""
    seen = {
        (record.tool_name, record.args_hash, record.result_hash)
        for record in current_run_state().evidence
    }
    for record in records:
        key = (record.tool_name, record.args_hash, record.result_hash)
        if key in seen:
            continue
        seen.add(key)
        current_run_state().evidence.append(record)
    return current_run_state().evidence


def reset_run_state() -> None:
    """Drop this turn's guard state and disclosure payload."""
    key = run_key()
    _run_states.pop(key, None)
    _run_disclosures.pop(key, None)


def _trim_registry[RegistryValue](registry: dict[str, RegistryValue]) -> None:
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
    *,
    has_claim: bool,
) -> None:
    """Publish the evidence tier the UI may show for this turn."""
    if not content.strip():
        return
    metadata = resolve_deliverable_tier(records, content=content)
    if not should_disclose_tier(metadata, has_claim=has_claim):
        return
    publish_disclosure(deliverable_tier=metadata.to_dict())


def attach_disclosure_to_event(event: dict[str, object], message_id: str) -> None:
    """Attach the turn's disclosure payload (if any) to a ``message_end`` event.

    The guard reads the turn key from the runtime ContextVar while the emitter
    knows the message id explicitly; a resumed or re-entered graph cycle can
    leave the guard on the unbound slot, so fall back to it. The unbound slot is
    cleared at every run start, which keeps the fallback turn-local.
    """
    disclosure = pop_run_disclosure(message_id) or pop_run_disclosure(UNBOUND_RUN_KEY)
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
    "record_evidence",
    "reset_run_state",
    "run_key",
]
