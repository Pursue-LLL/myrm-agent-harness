"""Skill failure tracking and telemetry for tool interception.

Publishes structured ``SkillFailureEvent`` when a tool call fails in a
session that has loaded storage skills.  Also counts the outcome of every
tool call into the run's skill usage (the Curator's ``.stats.json`` ledger)
while exactly one storage skill is loaded (the only case where the outcome
unambiguously belongs to that skill).
Counting never deactivates or repairs a skill by itself.

[INPUT]
- agent.errors.tool_error_category::ToolErrorCategory (POS: Canonical tool error categories for structured error classification.)
- agent.skill_agent (POS: loaded skills + task intent queries)
- runtime.events (POS: SkillFailureCandidate, SkillFailureEvent, event bus)
- backends.skills.usage_recorder (POS: run-scoped skill usage ledger)
- agent.middlewares._session_context (POS: approval session id)

[OUTPUT]
- track_skill_execution: Main entry — called after every tool call
- NON_SKILL_FAILURE_CATEGORIES: Categories that should not trigger events

[POS]
Skill failure telemetry — failure events plus single-skill outcome counting.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import TYPE_CHECKING

from myrm_agent_harness.agent.errors.tool_error_category import ToolErrorCategory
from myrm_agent_harness.agent.middlewares._session_context import (
    get_approval_session,
)
from myrm_agent_harness.utils.logger_utils import get_agent_logger

if TYPE_CHECKING:
    from myrm_agent_harness.runtime.events import SkillFailureCandidate

logger = get_agent_logger(__name__)

_SECRETISH_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_./+=:-]{32,}")

NON_SKILL_FAILURE_CATEGORIES: frozenset[str] = frozenset(
    {
        ToolErrorCategory.BENCHMARK_BLOCKED,
        ToolErrorCategory.CIRCUIT_BREAKER,
        ToolErrorCategory.CONTEXT_VALIDATION,
        ToolErrorCategory.ESTOP,
        ToolErrorCategory.FREQUENCY_GUARD,
        ToolErrorCategory.GUARDRAIL_BLOCKED,
        ToolErrorCategory.HOOK_BLOCKED,
        ToolErrorCategory.INVALID_TOOL,
        ToolErrorCategory.NETWORK_BLOCKED,
        ToolErrorCategory.PII_GUARD,
        ToolErrorCategory.POST_HOOK_BLOCKED,
        ToolErrorCategory.SANDBOX_BOUNDARY,
        ToolErrorCategory.SANDBOX_RO,
        ToolErrorCategory.STEERING,
        ToolErrorCategory.TOOL_CANCELLED,
        ToolErrorCategory.TRUST_ATTENUATION,
        ToolErrorCategory.TURN_BUDGET_GUARD,
        "any",
    }
)

# Loading a skill's SOP is the act of selecting it, not executing it, so its result says nothing about quality.
_SKILL_LOAD_TOOL_NAMES: frozenset[str] = frozenset({"skill_select_tool"})


def track_skill_execution(
    tool_name: str,
    *,
    tool_call_id: str,
    tool_args: dict[str, object],
    success: bool,
    error_message: str,
    error_category: str | None = None,
    loop_kind: str | None = None,
) -> None:
    """Publish structured failure events and count outcomes for the single loaded storage skill."""
    if tool_name in _SKILL_LOAD_TOOL_NAMES:
        return
    try:
        candidates = _build_skill_failure_candidates()
        if not candidates:
            return

        if not success:
            if not _should_publish_skill_failure(
                error_category=error_category,
                loop_kind=loop_kind,
            ):
                return
            sanitized_error = _sanitize_error_message(error_message)
            _publish_skill_failure_event(
                tool_name=tool_name,
                tool_call_id=tool_call_id,
                tool_args=tool_args,
                sanitized_error=sanitized_error,
                candidates=candidates,
                loop_kind=loop_kind,
            )
            _count_single_skill_outcome(candidates, success=False)
            return

        _count_single_skill_outcome(candidates, success=True)
    except Exception as exc:
        logger.debug("Skill execution tracking skipped: %s", exc)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _count_single_skill_outcome(candidates: tuple[SkillFailureCandidate, ...], *, success: bool) -> None:
    """Count one tool-call outcome for the only loaded storage skill (ambiguous owners are skipped)."""
    if len(candidates) != 1:
        return

    from myrm_agent_harness.backends.skills.usage_recorder import record_skill_execution

    record_skill_execution(candidates[0].skill_name, candidates[0].storage_path, success=success)


def _current_runtime_session_id() -> str | None:
    session_id = get_approval_session().strip()
    return session_id or None


def _should_publish_skill_failure(*, error_category: str | None, loop_kind: str | None) -> bool:
    if loop_kind:
        return True
    return error_category not in NON_SKILL_FAILURE_CATEGORIES


def _build_skill_failure_candidates() -> tuple[SkillFailureCandidate, ...]:
    from myrm_agent_harness.agent.skill_agent.context import get_loaded_skills
    from myrm_agent_harness.runtime.events import SkillFailureCandidate

    storage_skills = [skill for skill in get_loaded_skills() if skill.storage_skill_id]
    if not storage_skills:
        return ()

    if len(storage_skills) == 1:
        skill = storage_skills[0]
        return (
            SkillFailureCandidate(
                skill_id=skill.storage_skill_id or "",
                skill_name=skill.name,
                version=skill.version,
                storage_path=skill.storage_path,
                evolution_locked=skill.evolution_locked,
                confidence=1.0,
                reason="only_loaded_storage_skill",
            ),
        )

    candidates: list[SkillFailureCandidate] = []
    for index, skill in enumerate(storage_skills):
        is_latest = index == len(storage_skills) - 1
        candidates.append(
            SkillFailureCandidate(
                skill_id=skill.storage_skill_id or "",
                skill_name=skill.name,
                version=skill.version,
                storage_path=skill.storage_path,
                evolution_locked=skill.evolution_locked,
                confidence=0.65 if is_latest else 0.25,
                reason="latest_loaded_skill" if is_latest else "also_loaded_skill",
            )
        )
    return tuple(candidates)


def _publish_skill_failure_event(
    *,
    tool_name: str,
    tool_call_id: str,
    tool_args: dict[str, object],
    sanitized_error: str,
    candidates: tuple[SkillFailureCandidate, ...],
    loop_kind: str | None = None,
) -> None:
    from myrm_agent_harness.agent.skill_agent.context import get_task_intent
    from myrm_agent_harness.runtime.events import SkillFailureEvent, get_event_bus

    get_event_bus().publish(
        SkillFailureEvent(
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            tool_args_hash=_hash_tool_args(tool_args),
            error_message=sanitized_error,
            error_signature=_error_signature(tool_name, sanitized_error),
            candidates=candidates,
            loop_kind=loop_kind,
            session_id=_current_runtime_session_id(),
            task_intent=get_task_intent(),
        )
    )


def _sanitize_error_message(error_message: str) -> str:
    lines = [line.strip() for line in error_message.splitlines() if line.strip()]
    compact = " | ".join(lines[-3:]) if lines else error_message.strip()
    return _SECRETISH_TOKEN_PATTERN.sub("<redacted>", compact)[:1000]


def _error_signature(tool_name: str, error_message: str) -> str:
    tail = error_message.split("|")[-1].strip() if error_message else "unknown"
    normalized = re.sub(r"\s+", " ", tail)
    normalized = re.sub(r"\b\d{4,}\b", "<number>", normalized)
    normalized = _SECRETISH_TOKEN_PATTERN.sub("<redacted>", normalized)
    return f"{tool_name}:{normalized[:240]}"


def _hash_tool_args(tool_args: dict[str, object]) -> str:
    try:
        payload = json.dumps(tool_args, ensure_ascii=False, sort_keys=True, default=repr)
    except TypeError:
        payload = repr(tool_args)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
