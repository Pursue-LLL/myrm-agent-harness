"""Component Ablation Leverage & Harness Edit Rules Engine.

[INPUT]
- failure_mode: str | FailureMode (from trajectory_analysis)
- failure_counts: dict[str, int] (aggregated failure distribution)

[OUTPUT]
- ComponentTier: canonical component leverage hierarchy (TOOL > MIDDLEWARE > MEMORY > PROMPT)
- AblationRecommendation: structured recommendation with target config anchor
- derive_ablation_recommendations(): deterministic mapping from failure modes to high-ROI component edits

[POS]
Translates empirical ablation findings (Tools/Middleware >> Prompt) into actionable,
deterministic GUI guidance chips and configuration deep-links without incurring extra LLM cost.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field

from .trajectory_analysis import FailureMode


class ComponentTier(enum.StrEnum):
    """Component leverage hierarchy based on empirical ablation ROI."""

    TOOL = "tool"
    MIDDLEWARE = "middleware"
    MEMORY = "memory"
    PROMPT = "prompt"


@dataclass(frozen=True, slots=True)
class AblationRecommendation:
    """Actionable component recommendation derived from failure trajectory signatures."""

    component: ComponentTier
    priority: int  # 1 (Highest ROI) -> 4 (Lowest ROI)
    action_key: str
    title: str
    reason: str
    target_config_tab: str  # e.g. "capabilities", "security", "basic"
    target_setting_key: str  # e.g. "tool_repair", "context_compression", "skills"
    affected_case_count: int = 0
    evidence_modes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "component": self.component.value,
            "priority": self.priority,
            "action_key": self.action_key,
            "title": self.title,
            "reason": self.reason,
            "target_config_tab": self.target_config_tab,
            "target_setting_key": self.target_setting_key,
            "affected_case_count": self.affected_case_count,
            "evidence_modes": list(self.evidence_modes),
        }


# Canonical mapping from Trajectory FailureMode to high-ROI component remediation
_FAILURE_TO_ABLATION_MAP: dict[
    str, tuple[ComponentTier, int, str, str, str, str, str]
] = {
    FailureMode.TOOL_SELECTION_ERROR.value: (
        ComponentTier.TOOL,
        1,
        "bind_missing_tool_or_skill",
        "Tool Selection Defect",
        "Agent failed to locate or invoked non-existent tools. Bind relevant skill or tool definition in capabilities.",
        "capabilities",
        "skills",
    ),
    FailureMode.TOOL_ARGUMENT_MALFORMED.value: (
        ComponentTier.MIDDLEWARE,
        1,
        "enable_argument_repair_middleware",
        "Tool Argument Serialization Failure",
        "Model generated invalid parameters. Enable argument validation and repair middleware rather than expanding prompt.",
        "capabilities",
        "tool_interceptor",
    ),
    FailureMode.CONTEXT_OVERFLOW_OR_BUDGET.value: (
        ComponentTier.MIDDLEWARE,
        2,
        "enable_context_compression",
        "Context Window Saturation",
        "Trajectory exceeded token or turn budget. Enable idle compact or adaptive context compression middleware.",
        "capabilities",
        "context_compression",
    ),
    FailureMode.EXECUTION_TIMEOUT.value: (
        ComponentTier.MIDDLEWARE,
        2,
        "adjust_execution_budget",
        "Sandbox Command Timeout",
        "Sandbox operations timed out. Enable parallel fission or increase max iteration budget.",
        "capabilities",
        "max_iterations",
    ),
    FailureMode.DESTRUCTIVE_OR_REGRESSIVE.value: (
        ComponentTier.MIDDLEWARE,
        2,
        "enable_security_guardrails",
        "Destructive Workspace Action",
        "Agent attempted destructive edits or regressed prior state. Enforce workspace policy and safety interceptors.",
        "security",
        "workspace_policy",
    ),
    FailureMode.DECONTAM_VIOLATION.value: (
        ComponentTier.MIDDLEWARE,
        1,
        "enforce_sandbox_isolation",
        "Benchmark Canary Probe",
        "Agent probed canary tokens or benchmark assets. Enforce strict sandbox isolation.",
        "security",
        "sandbox_isolation",
    ),
    FailureMode.HARDCODED_TESTS.value: (
        ComponentTier.PROMPT,
        4,
        "tune_persona_objective",
        "Reward Hacking Attempt",
        "Agent generated brittle mocks to bypass checks. Refine core prompt task objective.",
        "basic",
        "system_prompt",
    ),
    FailureMode.INTENT_MISUNDERSTANDING.value: (
        ComponentTier.PROMPT,
        4,
        "tune_persona_objective",
        "Constraint Misalignment",
        "Agent failed core task objective. Refine role description and constraints in system prompt.",
        "basic",
        "system_prompt",
    ),
    FailureMode.UNHANDLED_RUNTIME_EXCEPTION.value: (
        ComponentTier.MIDDLEWARE,
        2,
        "enable_error_recovery_middleware",
        "Unhandled Runtime Crash",
        "Agent crashed on unexpected exceptions. Enable exception recovery interceptor.",
        "capabilities",
        "delivery_assurance",
    ),
}


def derive_ablation_recommendations(
    failure_counts: dict[str, int],
) -> list[AblationRecommendation]:
    """Derive deterministic, high-ROI component recommendations from failure distribution.

    Args:
        failure_counts: Mapping of failure mode string values to their occurrence count.

    Returns:
        Sorted list of AblationRecommendation ordered by priority (ROI) ascending
        and affected_case_count descending.
    """
    if not failure_counts:
        return []

    recs_by_action: dict[str, AblationRecommendation] = {}

    for mode_str, count in failure_counts.items():
        if count <= 0:
            continue
        mapping = _FAILURE_TO_ABLATION_MAP.get(mode_str)
        if not mapping:
            # Fallback for unmapped failure modes to prevent measurement decay
            mapping = (
                ComponentTier.MIDDLEWARE,
                2,
                "enable_error_recovery_middleware",
                "Unhandled Failure Signature",
                f"Observed unmapped failure signature ({mode_str}). Enable error recovery middleware.",
                "capabilities",
                "delivery_assurance",
            )

        tier, priority, action_key, title, reason, target_tab, target_key = mapping

        if action_key in recs_by_action:
            existing = recs_by_action[action_key]
            updated_modes = list(existing.evidence_modes)
            if mode_str not in updated_modes:
                updated_modes.append(mode_str)
            recs_by_action[action_key] = AblationRecommendation(
                component=existing.component,
                priority=existing.priority,
                action_key=existing.action_key,
                title=existing.title,
                reason=existing.reason,
                target_config_tab=existing.target_config_tab,
                target_setting_key=existing.target_setting_key,
                affected_case_count=existing.affected_case_count + count,
                evidence_modes=updated_modes,
            )
        else:
            recs_by_action[action_key] = AblationRecommendation(
                component=tier,
                priority=priority,
                action_key=action_key,
                title=title,
                reason=reason,
                target_config_tab=target_tab,
                target_setting_key=target_key,
                affected_case_count=count,
                evidence_modes=[mode_str],
            )

    # Sort by priority ascending (1 is highest ROI), then affected count descending
    return sorted(
        recs_by_action.values(),
        key=lambda r: (r.priority, -r.affected_case_count),
    )
