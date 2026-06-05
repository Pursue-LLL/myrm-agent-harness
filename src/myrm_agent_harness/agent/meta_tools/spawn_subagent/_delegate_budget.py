"""Budget admission, policy enforcement, result caching, and dynamic description for delegate_task.

[INPUT]
- sub_agents.types::ControlScope, DelegateRole, SubagentCatalog (POS: Subagent type definitions)
- runtime.events.system_events::DelegationPolicyDecision (POS: System event DTOs)
- utils.token_economics (POS: Budget guard and cost engine)

[OUTPUT]
- _CachedResult, _cache_key, _get_cached, _put_cache: Result caching with TTL
- _get_hashable_value, _compute_payload_hash: Payload fingerprinting (deadlock detection)
- _normalize_role: DelegateRole normalization
- _BatchBudgetAdmission: Budget admission result
- _emit_policy_denial_event, _policy_denied: Policy denial helpers
- _resolve_model_name, _estimate_prompt_tokens, _get_budget_checker: Budget utilities
- _admit_race_budget: Batch budget admission
- _build_dynamic_description: Dynamic tool description builder

[POS]
Budget, policy, caching, and description utilities for the delegate_task tool family.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from myrm_agent_harness.agent.sub_agents.types import (
    ControlScope,
    DelegateRole,
    SubagentCatalog,
)
from myrm_agent_harness.runtime.events.system_events import (
    DelegationPolicyDecision,
    SubagentLifecycleData,
)
from myrm_agent_harness.utils.logger_utils import get_agent_logger
from myrm_agent_harness.utils.token_economics.budget_guard import BudgetStatus
from myrm_agent_harness.utils.token_economics.cost_engine import compute_cost_by_tokens

if TYPE_CHECKING:
    from myrm_agent_harness.agent.base_agent import BaseAgent
    from myrm_agent_harness.agent.meta_tools.spawn_subagent._delegate_batch import (
        TaskRequest,
    )

logger = get_agent_logger(__name__)

_CACHE_TTL_SECONDS = 60
_CACHE_MAX_SIZE = 1000


# ---------------------------------------------------------------------------
# Result cache
# ---------------------------------------------------------------------------


class _CachedResult:
    __slots__ = ("data", "timestamp")

    def __init__(self, data: object, timestamp: float) -> None:
        self.data = data
        self.timestamp = timestamp


_result_cache: dict[str, _CachedResult] = {}


def _cache_key(
    agent_type: str,
    task: str,
    context: dict[str, object] | None,
    session_id: str = "",
    role: str = DelegateRole.LEAF.value,
) -> str:
    raw = f"{session_id}::{agent_type}::{role}::{task}::{sorted((context or {}).items())}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _get_cached(key: str) -> object | None:
    entry = _result_cache.get(key)
    if entry and (time.time() - entry.timestamp) < _CACHE_TTL_SECONDS:
        return entry.data
    if entry:
        del _result_cache[key]
    return None


def _put_cache(key: str, data: object) -> None:
    now = time.time()
    expired = [k for k, v in _result_cache.items() if (now - v.timestamp) > _CACHE_TTL_SECONDS]
    for k in expired:
        del _result_cache[k]
    if len(_result_cache) >= _CACHE_MAX_SIZE:
        oldest = min(_result_cache, key=lambda k: _result_cache[k].timestamp)
        del _result_cache[oldest]
    _result_cache[key] = _CachedResult(data, now)


def _get_hashable_value(v: object) -> object:
    """Recursively ensure a value is JSON-serializable and order-independent."""
    if isinstance(v, dict):
        return {str(k): _get_hashable_value(val) for k, val in v.items()}
    if isinstance(v, list | tuple):
        return [_get_hashable_value(val) for val in v]
    if isinstance(v, int | float | str | bool | type(None)):
        return v
    return str(v)


def _compute_payload_hash(
    agent_type: str,
    task: str,
    role_value: str,
    context: dict[str, object] | None,
) -> str:
    """Compute a SHA-256 fingerprint for a delegation payload (deadlock detection)."""
    import json as _json

    hashable_ctx = _get_hashable_value(context) if context else {}
    payload_str = _json.dumps(
        {
            "type": str(agent_type).strip(),
            "task": str(task).strip(),
            "role": role_value,
            "ctx": hashable_ctx,
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(payload_str.encode("utf-8")).hexdigest()


def _normalize_role(role: DelegateRole | str) -> DelegateRole:
    if isinstance(role, DelegateRole):
        return role
    try:
        return DelegateRole(str(role))
    except ValueError:
        return DelegateRole.LEAF


# ---------------------------------------------------------------------------
# Budget admission
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _BatchBudgetAdmission:
    status: Literal["admitted", "downgraded", "unavailable"]
    reason: str
    estimated_cost_usd: float | None = None
    remaining_budget_usd: float | None = None
    cost_status: str = "unknown"

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "reason": self.reason,
            "estimated_cost_usd": self.estimated_cost_usd,
            "remaining_budget_usd": self.remaining_budget_usd,
            "cost_status": self.cost_status,
        }


# ---------------------------------------------------------------------------
# Policy denial
# ---------------------------------------------------------------------------


def _emit_policy_denial_event(
    *,
    task_id: str,
    session_id: str,
    decision: DelegationPolicyDecision,
) -> None:
    try:
        from myrm_agent_harness.runtime.events import (
            SubagentLifecycleEvent,
            get_event_bus,
        )

        get_event_bus().publish(
            SubagentLifecycleEvent(
                event_name="policy_denied",
                task_id=task_id,
                session_id=session_id,
                data=SubagentLifecycleData(
                    agent_type=decision.agent_type,
                    role=decision.requested_role,
                    control_scope=decision.effective_scope,
                    status="policy_denied",
                    policy=decision,
                ),
            )
        )
    except Exception as exc:
        logger.warning("Failed to emit subagent policy denial event: %s", exc)


def _policy_denied(
    *,
    reason: str,
    requested_role: DelegateRole,
    effective_scope: ControlScope,
    agent_type: str,
    task_id: str,
    session_id: str,
    details: str,
) -> dict[str, object]:
    decision = DelegationPolicyDecision(
        allowed=False,
        reason=reason,
        requested_role=requested_role.value,
        effective_scope=effective_scope.value,
        agent_type=agent_type,
        details=details,
    )
    _emit_policy_denial_event(
        task_id=task_id,
        session_id=session_id,
        decision=decision,
    )
    return {
        "success": False,
        "status": "policy_denied",
        "reason": reason,
        "requested_role": requested_role.value,
        "effective_scope": effective_scope.value,
        "policy_decision": decision.to_dict(),
        "error": details,
    }


# ---------------------------------------------------------------------------
# Model / token estimation
# ---------------------------------------------------------------------------


def _resolve_model_name(parent_agent: BaseAgent, config_model: str | None) -> str | None:
    if config_model:
        return config_model
    llm = getattr(parent_agent, "llm", None)
    for attr_name in ("model_name", "model", "model_id", "deployment_name"):
        value = getattr(llm, attr_name, None)
        if isinstance(value, str) and value:
            return value
    return None


def _estimate_prompt_tokens(task: TaskRequest) -> int:
    text = task.objective
    if task.context_files:
        text += "\n".join(task.context_files)
    if task.context:
        text += str(task.context)
    return max(1, (len(text) + 3) // 4)


def _get_budget_checker(parent_agent: BaseAgent) -> object | None:
    tracker = getattr(parent_agent, "token_tracker", None)
    checker = getattr(tracker, "budget_checker", None)
    if checker is not None and (
        callable(getattr(checker, "check_budget", None)) or callable(getattr(checker, "get_remaining_budget", None))
    ):
        return checker
    parent_checker = getattr(parent_agent, "budget_checker", None)
    if parent_checker is not None and (
        callable(getattr(parent_checker, "check_budget", None))
        or callable(getattr(parent_checker, "get_remaining_budget", None))
    ):
        return parent_checker
    return None


async def _admit_race_budget(
    *,
    parent_agent: BaseAgent,
    catalog: SubagentCatalog,
    tasks: list[TaskRequest],
) -> _BatchBudgetAdmission:
    checker = _get_budget_checker(parent_agent)
    remaining_budget_usd = None
    if checker is not None and hasattr(checker, "get_remaining_budget"):
        remaining = checker.get_remaining_budget()
        if isinstance(remaining, int | float):
            remaining_budget_usd = float(remaining)

    estimated_costs: list[float] = []
    cost_status = "unknown"
    for task in tasks:
        config = await catalog.resolve(task.agent_type)
        if config is None:
            return _BatchBudgetAdmission(
                status="unavailable",
                reason="agent_config_unavailable",
                remaining_budget_usd=remaining_budget_usd,
            )
        if config.max_cost_usd is not None:
            estimated_costs.append(float(config.max_cost_usd))
            cost_status = "configured_max_cost"
            continue
        if config.budget_tokens is None:
            return _BatchBudgetAdmission(
                status="unavailable",
                reason="task_budget_unconfigured",
                remaining_budget_usd=remaining_budget_usd,
            )
        model_name = _resolve_model_name(parent_agent, config.model)
        prompt_tokens = _estimate_prompt_tokens(task)
        completion_tokens = max(0, int(config.budget_tokens) - prompt_tokens)
        cost = compute_cost_by_tokens(
            model=model_name,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )
        if not cost.is_known:
            return _BatchBudgetAdmission(
                status="unavailable",
                reason="model_cost_unavailable",
                remaining_budget_usd=remaining_budget_usd,
            )
        estimated_costs.append(cost.usd)
        cost_status = cost.status.value

    estimated_cost_usd = sum(estimated_costs)

    if checker is not None and hasattr(checker, "check_budget"):
        budget_status = checker.check_budget(estimated_cost_usd)
        if isinstance(budget_status, str):
            try:
                budget_status = BudgetStatus(budget_status)
            except ValueError:
                budget_status = BudgetStatus.OK
        if budget_status in {BudgetStatus.FINALIZATION, BudgetStatus.EXCEEDED}:
            return _BatchBudgetAdmission(
                status="downgraded",
                reason=f"budget_status_{budget_status.value}",
                estimated_cost_usd=estimated_cost_usd,
                remaining_budget_usd=remaining_budget_usd,
                cost_status=cost_status,
            )
    if remaining_budget_usd is not None and remaining_budget_usd < estimated_cost_usd:
        return _BatchBudgetAdmission(
            status="downgraded",
            reason="remaining_budget_insufficient",
            estimated_cost_usd=estimated_cost_usd,
            remaining_budget_usd=remaining_budget_usd,
            cost_status=cost_status,
        )
    return _BatchBudgetAdmission(
        status="admitted",
        reason="within_budget",
        estimated_cost_usd=estimated_cost_usd,
        remaining_budget_usd=remaining_budget_usd,
        cost_status=cost_status,
    )


# ---------------------------------------------------------------------------
# Dynamic tool description
# ---------------------------------------------------------------------------


async def _build_dynamic_description(catalog: SubagentCatalog, allowed_types: list[str] | None) -> str:
    """Generate tool description including available subagent types."""
    available_ids = await catalog.list_available()
    visible_ids = [tid for tid in available_ids if tid in allowed_types] if allowed_types is not None else available_ids

    lines = [
        "Delegate tasks to specialized subagents that run asynchronously.",
        "",
        "## Available agent types",
    ]

    display_ids = visible_ids[:50]
    for type_id in display_ids:
        cfg = await catalog.resolve(type_id)
        if cfg:
            label = f"{cfg.display_name} ({type_id})" if cfg.display_name else type_id
            desc = cfg.description or cfg.system_prompt[:80]
            lines.append(f"- '{type_id}': [{label}] {desc}")

    if len(visible_ids) > 50:
        lines.append(f"... and {len(visible_ids) - 50} more custom agents.")

    lines.extend(
        [
            "",
            "## When to delegate",
            "Only delegate when at least ONE applies:",
            "1. Parallel gain: 2+ independent sub-tasks with non-trivial integration",
            "2. Specialized expertise: task requires knowledge/tools you lack",
            "3. Adversarial breadth: multiple independent approaches needed",
            "If NONE → do it yourself. Delegation adds orchestration overhead.",
            "",
            "## When NOT to delegate",
            "- Ultra-simple: single file read, quick edit, one command",
            "- Sequential dependencies: steps must run in order",
            "- Overhead exceeds task value",
            "",
            "## Parameters",
            "- agent_type: One of the available types above, or any valid custom agent ID",
            "- objective: Clear description of the core objective for the subagent",
            "- context_files: List of relevant file paths or resources for this task",
            "- context: Optional context data (dict) to pass",
            "- wait: If true, wait for result synchronously; if false, return task_id for later retrieval",
            "- role: 'leaf' by default. Use 'orchestrator' only for trusted coordinator agents.",
            "",
            "## Usage patterns",
            "1. Parallel: spawn with wait=false; check results with list_subagents_tool",
            "2. Synchronous: spawn with wait=true for immediate result",
            "3. Results are cached for 60s to avoid redundant executions",
            "",
            "## CRITICAL: Active result retrieval",
            "Async results (wait=false) stored in memory, NOT auto-injected.",
            "MUST call list_subagents_tool after spawning to retrieve results.",
            "Preserves prompt cache (10x cost savings).",
        ]
    )
    return "\n".join(lines)
