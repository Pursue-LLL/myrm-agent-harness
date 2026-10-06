# [POS] toolkits/memory/strategies/hindsight/counterfactual_extractor.py
# [INPUT] uuid, FailureTurn, FailureTrajectory, HindsightRule
# [OUTPUT] CounterfactualRuleExtractor

"""Counterfactual rule extractor deriving actionable hindsight lessons from failure trajectories."""

from __future__ import annotations

import uuid

from myrm_agent_harness.toolkits.memory.strategies.hindsight.types import (
    FailureTrajectory,
    FailureTurn,
    HindsightRule,
)


class CounterfactualRuleExtractor:
    """Performs counterfactual reasoning to extract mistake signatures and proactive corrections."""

    def extract_rule(
        self,
        trajectory: FailureTrajectory,
        turning_point: FailureTurn | None = None,
    ) -> HindsightRule:
        """Derive a structured hindsight rule from a failed trajectory."""
        tp = turning_point or (trajectory.turns[-1] if trajectory.turns else None)
        rule_id = f"rule-{uuid.uuid4().hex[:8]}"

        if not tp:
            # Degenerate case: trajectory had no recorded turns, fallback to terminal error
            return HindsightRule(
                rule_id=rule_id,
                task_pattern=trajectory.task_goal or "general_task",
                mistake_signature=trajectory.terminal_error or "unspecified_failure",
                correction_advice="Validate preconditions and verify tool parameters before retrying.",
                tags=["general", "fallback"],
                confidence=0.5,
                hit_count=1,
            )

        tool = tp.tool_name
        err_msg = (
            f"{tp.error_message} | {tp.tool_output} | {trajectory.terminal_error}".strip()
        )
        err_lower = err_msg.lower()

        # Heuristic pattern classification & counterfactual recommendation
        tags: list[str] = [tool.lower()]
        confidence = 0.9

        if (
            "permission denied" in err_lower
            or "operation not permitted" in err_lower
            or "eacces" in err_lower
            or "eperm" in err_lower
        ):
            mistake_sig = f"Attempted '{tool}' without requisite filesystem/execution permissions."
            correction = (
                f"Check file permissions, verify current user credentials, or ensure target directory "
                f"is writable before invoking '{tool}'."
            )
            tags.extend(["permission", "security"])
        elif "not found" in err_lower or "enoent" in err_lower:
            mistake_sig = f"Invoked '{tool}' targeting missing binary, file path, or resource."
            correction = (
                "Verify target path or dependency existence prior to execution; create parent directories "
                "or install missing tools first."
            )
            tags.extend(["not_found", "path"])
        elif "timeout" in err_lower or "timed out" in err_lower:
            mistake_sig = f"Action '{tool}' hung or exceeded deadline waiting for external completion."
            correction = (
                "Set explicit non-blocking flags, increase timeout threshold, or decouple execution "
                "into asynchronous background monitoring."
            )
            tags.extend(["timeout", "concurrency"])
        elif "unauthorized" in err_lower or "401" in err_lower or "403" in err_lower:
            mistake_sig = f"Invoked '{tool}' with missing or expired authentication token/credentials."
            correction = (
                f"Validate authentication headers and refresh active session tokens prior to invoking '{tool}'."
            )
            tags.extend(["auth", "credential"])
        else:
            # General operational failure
            mistake_sig = f"Failed execution on tool '{tool}' with diagnostic: {err_msg[:120]}."
            correction = (
                f"Inspect '{tool}' input parameters for schema violations and confirm environment state."
            )
            tags.append("execution")
            confidence = 0.75

        # Task pattern combining goal keywords and tool identity
        task_pattern = f"[{tool}] {trajectory.task_goal}" if trajectory.task_goal else f"[{tool}] task"

        return HindsightRule(
            rule_id=rule_id,
            task_pattern=task_pattern,
            mistake_signature=mistake_sig,
            correction_advice=correction,
            tags=tags,
            confidence=confidence,
            hit_count=1,
        )
