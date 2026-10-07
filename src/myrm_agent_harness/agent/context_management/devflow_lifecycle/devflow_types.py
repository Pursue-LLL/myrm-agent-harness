"""Data contracts and schemas for DevFlow context lifecycle and progressive loading.

Defines the 5-phase engineering lifecycle, the 4-Question context gate questionnaire,
and structured exploration handoff contracts under strict token constraints.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class DevFlowPhase(StrEnum):
    """Sequential phases of a software development workflow lifecycle."""

    PLANNING = "planning"
    EXPLORATION = "exploration"
    IMPLEMENTATION = "implementation"
    VERIFICATION = "verification"
    DELIVERY = "delivery"


class ContextAdmissionDecision(StrEnum):
    """Decision rendered by the 4-Question Gate on whether information enters the primary context."""

    INLINE_ALLOW = "inline_allow"
    ISOLATE_SCRATCHPAD = "isolate_scratchpad"
    DEFER_PROGRESSIVE = "defer_progressive"
    EXTERNAL_REFERENCE_ONLY = "external_reference_only"


@dataclass(frozen=True)
class GateQuestionnaireEvaluation:
    """Outcome of evaluating candidate content against the 4-Question Gate."""

    is_required_for_current_phase: bool
    is_single_use_reference: bool
    has_explicit_trigger_condition: bool
    can_be_retrieved_externally: bool
    decision: ContextAdmissionDecision
    rationale: str


@dataclass(frozen=True)
class StructuredExplorationHandoff:
    """Rigid, token-bounded (<= 500 chars) structured synthesis from transient exploration phases."""

    target_components: list[str]
    key_findings: list[str]
    impacted_files: list[str]
    architectural_risks: list[str]
    direct_verdict: str
    token_count_estimate: int
    is_within_bound: bool = True

    def render_markdown_card(self) -> str:
        """Render compact markdown card for downstream implementation phases."""
        lines = [
            "### 🔍 Exploration Handoff Synthesis",
            f"**Verdict**: {self.direct_verdict}",
            f"**Components**: {', '.join(self.target_components)}",
            f"**Impacted Files**: {', '.join(self.impacted_files)}",
            "**Key Findings**:",
        ]
        for f in self.key_findings:
            lines.append(f"- {f}")
        if self.architectural_risks:
            lines.append("**Risks**:")
            for r in self.architectural_risks:
                lines.append(f"- ⚠️ {r}")
        return "\n".join(lines)


@dataclass(frozen=True)
class PhaseLifecycleState:
    """Current state of active DevFlow phase and associated context manifests."""

    session_id: str
    current_phase: DevFlowPhase
    active_deliverable_templates: list[str]
    retained_handoffs: list[StructuredExplorationHandoff]
    purged_raw_tokens_count: int
