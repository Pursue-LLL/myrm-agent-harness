"""Goal drift detection for continuation guard chain.

[INPUT]
- .protocols::GoalProvider (POS: Goal provider protocol)
- .types::ContinuationDecision, GoalStatus, Goal (POS: Guard chain result)
- langchain_core.messages::BaseMessage, HumanMessage (POS: Message types)

[OUTPUT]
- check_goal_drift: Evaluates trajectory drift, returns ContinuationDecision or None.

[POS]
Goal drift detection — lightweight LLM judge that scores how well recent tool calls
align with the stated objective. Produces drift_nudge (soft) or drift_pause (hard)
verdicts consumed by the continuation guard chain. Fail-open on errors.
"""

from __future__ import annotations

import json as _json
import logging
import re as _re
from typing import TYPE_CHECKING

from langchain_core.messages import BaseMessage, HumanMessage

from .types import ContinuationDecision, GoalStatus

if TYPE_CHECKING:
    from .protocols import GoalProvider
    from .types import Goal

logger = logging.getLogger(__name__)

_DRIFT_CHECK_INTERVAL = 5
_DRIFT_NUDGE_THRESHOLD = 3
_DRIFT_PAUSE_THRESHOLD = 7
_DRIFT_JUDGE_MAX_CHARS = 2000


def _extract_recent_tool_summary(messages: list[BaseMessage], window: int = 5) -> str:
    """Extract a brief summary of recent tool calls for drift evaluation."""
    from langchain_core.messages import ToolMessage as LCToolMessage

    summaries: list[str] = []
    for msg in reversed(messages):
        if isinstance(msg, LCToolMessage):
            name = getattr(msg, "name", "unknown")
            content = msg.content if isinstance(msg.content, str) else str(msg.content)
            summaries.append(f"[{name}] {content[:200]}")
            if len(summaries) >= window:
                break

    summaries.reverse()
    return "\n".join(summaries)[:_DRIFT_JUDGE_MAX_CHARS]


def _parse_drift_score(reason: str) -> int | None:
    """Extract drift_score integer from judge response."""
    json_match = _re.search(r"\{[^}]*\"drift_score\"\s*:\s*(\d+)[^}]*\}", reason)
    if json_match:
        try:
            return int(json_match.group(1))
        except (ValueError, IndexError):
            pass

    try:
        parsed = _json.loads(reason)
        if isinstance(parsed, dict) and "drift_score" in parsed:
            return int(parsed["drift_score"])
    except (ValueError, TypeError, _json.JSONDecodeError):
        pass

    return None


def _make_decision(
    verdict: str,
    reason: str,
    goal: Goal,
    *,
    message: str | None = None,
) -> ContinuationDecision:
    """Build a ContinuationDecision for drift verdicts."""
    return ContinuationDecision(
        should_continue=(verdict == "drift_nudge"),
        verdict=verdict,  # type: ignore[arg-type]
        reason=reason,
        turns_used=goal.turns_used,
        max_turns=goal.budget.max_turns if goal.budget else None,
        message=message or "",
    )


async def check_goal_drift(
    goal_provider: GoalProvider,
    goal: Goal,
    collected_messages: list[BaseMessage],
) -> ContinuationDecision | None:
    """Evaluate whether recent agent actions are drifting from the goal objective.

    Returns None if no drift detected or check not applicable.
    Returns a ContinuationDecision with drift_nudge or drift_pause verdict otherwise.

    Uses the same lightweight LLM judge as semantic completion (evaluate_semantic),
    but with a drift-specific prompt. Fail-open: errors default to no drift.
    """
    if goal.turns_used % _DRIFT_CHECK_INTERVAL != 0:
        return None

    tool_summary = _extract_recent_tool_summary(collected_messages)
    if not tool_summary.strip():
        return None

    objective_snippet = goal.objective[:500]
    criteria = (
        "You are a drift detector. Given the user's goal and the agent's recent "
        "tool calls, rate how relevant the recent work is to the stated goal.\n\n"
        f"Goal: {objective_snippet}\n\n"
        f"Recent tool calls:\n{tool_summary}\n\n"
        "Rate drift from 0 (perfectly on-target) to 10 (completely off-target).\n"
        'Reply ONLY with JSON: {"drift_score": <0-10>, "reason": "one sentence"}'
    )

    try:
        result = await goal_provider.evaluate_semantic(criteria, tool_summary)
        if result.parse_failed:
            return None

        raw_reason = result.reason or ""
        score = _parse_drift_score(raw_reason)
        if score is None:
            return None

        logger.info(
            "Goal %s drift check: score=%d (threshold nudge=%d, pause=%d)",
            goal.goal_id,
            score,
            _DRIFT_NUDGE_THRESHOLD,
            _DRIFT_PAUSE_THRESHOLD,
        )

        if score >= _DRIFT_PAUSE_THRESHOLD:
            await goal_provider.update_status(goal.goal_id, GoalStatus.PAUSED)
            await goal_provider.update_metadata(
                goal.goal_id,
                {"pause_reason": f"Goal drift detected (score={score}): {raw_reason[:200]}"},
            )
            return _make_decision(
                "drift_pause",
                f"Goal drift detected (score={score}/10) — paused for human review",
                goal,
            )

        if score >= _DRIFT_NUDGE_THRESHOLD:
            nudge_msg = (
                f"[DRIFT WARNING] Your recent actions appear to be drifting from the goal "
                f"(drift score: {score}/10). Refocus on: {objective_snippet[:120]}"
            )
            collected_messages.append(HumanMessage(content=nudge_msg, name="developer"))
            return _make_decision("drift_nudge", f"Drift nudge injected (score={score})", goal, message=nudge_msg)

    except NotImplementedError:
        pass
    except Exception:
        logger.warning("Drift check error for goal %s — skipping (fail-open)", goal.goal_id, exc_info=True)

    return None
