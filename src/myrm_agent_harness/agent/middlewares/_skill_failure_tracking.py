"""Skill failure tracking and telemetry for tool interception.

Publishes structured ``SkillFailureEvent`` when a tool call fails in a
session that has loaded storage skills.  Also records successful
executions for skill evolution feedback.

[INPUT]
- agent.skill_agent (POS: loaded skills + task intent queries)
- runtime.events (POS: SkillFailureCandidate, SkillFailureEvent, event bus)
- agent.skills.evolution (POS: global evolution integration)
- agent.middlewares._session_context (POS: approval session id)

[OUTPUT]
- track_skill_execution: Main entry — called after every tool call
- NON_SKILL_FAILURE_CATEGORIES: Categories that should not trigger events

[POS]
Skill failure telemetry — tracking, analysis, and deactivation of
underperforming skills based on failure rate thresholds.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from typing import TYPE_CHECKING

from myrm_agent_harness.agent.middlewares._session_context import (
    get_approval_session,
)
from myrm_agent_harness.utils.logger_utils import get_agent_logger

if TYPE_CHECKING:
    from myrm_agent_harness.runtime.events import SkillFailureCandidate

logger = get_agent_logger(__name__)

_SECRETISH_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_./+=:-]{32,}")

NON_SKILL_FAILURE_CATEGORIES = frozenset(
    {
        "circuit_breaker",
        "context_validation",
        "estop",
        "frequency_guard",
        "hook_blocked",
        "invalid_tool",
        "network_blocked",
        "pii_guard",
        "post_hook_blocked",
        "sandbox_ro",
        "steering",
        "tool_cancelled",
        "trust_attenuation",
        "any",
    }
)


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
    """Track storage skill success and publish structured runtime failure events."""
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
            _publish_skill_failure_event(
                tool_name=tool_name,
                tool_call_id=tool_call_id,
                tool_args=tool_args,
                error_message=error_message,
                candidates=candidates,
                loop_kind=loop_kind,
            )
            return

        from myrm_agent_harness.agent.skills.evolution.infra.integration import (
            get_global_evolution_integration,
        )

        if len(candidates) != 1:
            return

        evolution = get_global_evolution_integration()
        if not evolution:
            return

        candidate = candidates[0]
        tracking_task = asyncio.create_task(evolution.record_execution(skill_id=candidate.skill_id, success=True))
        tracking_task.add_done_callback(_log_skill_tracking_task_failure)
    except Exception as exc:
        logger.debug("Skill execution tracking skipped: %s", exc)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _log_skill_tracking_task_failure(task: asyncio.Task[None]) -> None:
    try:
        task.result()
    except asyncio.CancelledError:
        return
    except Exception as exc:
        logger.debug("Skill execution tracking task failed: %s", exc)


def _current_runtime_session_id() -> str | None:
    session_id = get_approval_session().strip()
    return session_id or None


def _should_publish_skill_failure(*, error_category: str | None, loop_kind: str | None) -> bool:
    if loop_kind:
        return True
    return error_category not in NON_SKILL_FAILURE_CATEGORIES


def _build_skill_failure_candidates() -> tuple[SkillFailureCandidate, ...]:
    from myrm_agent_harness.agent._skill_agent_context import get_loaded_skills
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
    error_message: str,
    candidates: tuple[SkillFailureCandidate, ...],
    loop_kind: str | None = None,
) -> None:
    from myrm_agent_harness.agent._skill_agent_context import get_task_intent
    from myrm_agent_harness.runtime.events import SkillFailureEvent, get_event_bus

    sanitized_error = _sanitize_error_message(error_message)
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
