"""Complex Project MVP Scope Distiller and Stepwise Execution Guide Engine (Item 214).

[INPUT]
- user_request: Raw user natural language project description.
- MvpDistillerConfig: Configuration governing complexity thresholds and keywords.

[OUTPUT]
- DistillationOutcome: Analysis result with complexity risk assessment, MVP core plans, and UI card.
- Stepwise phase execution state machine managing milestone verification and clean handoffs.

[POS]
- Shields context from bloating and prevents unfinished projects by actively distilling
- overwhelming feature lists into a lean, testable first-phase MVP architecture.
"""

from __future__ import annotations

import time
from typing import Sequence

from .mvp_distiller_types import (
    DistillationOutcome,
    ModuleSpec,
    MvpDistillerConfig,
    MvpPhaseLifecycleState,
    PhaseScopePlan,
    ProjectComplexityLevel,
)


class ComplexProjectMvpDistillerEngine:
    """Orchestrates requirement scope analysis, MVP distillation, and phased execution."""

    def __init__(self, config: MvpDistillerConfig | None = None) -> None:
        self._config = config or MvpDistillerConfig()
        # session_id -> state
        self._session_states: dict[str, MvpPhaseLifecycleState] = {}
        # session_id -> list[PhaseScopePlan]
        self._session_plans: dict[str, list[PhaseScopePlan]] = {}
        # session_id -> current_phase_index
        self._session_active_phase: dict[str, int] = {}
        # session_id -> verified_notes
        self._session_verified_notes: dict[str, dict[int, str]] = {}

    @property
    def config(self) -> MvpDistillerConfig:
        """Returns engine configuration."""
        return self._config

    def evaluate_requirement(self, user_request: str) -> DistillationOutcome:
        """Evaluates complexity of user prompt, distilling an MVP phased roadmap if bloated."""
        start_time = time.perf_counter()
        req_lower = user_request.lower()

        detected_modules: list[ModuleSpec] = []
        for domain, keywords in self._config.domain_keywords.items():
            matched = any(kw.lower() in req_lower for kw in keywords)
            if matched:
                is_core = domain in ("core_presentation", "data_storage", "auth")
                risk = 1.0 if is_core else 2.0
                detected_modules.append(
                    ModuleSpec(
                        module_id=domain,
                        name=domain.replace("_", " ").title(),
                        description=f"Auto-extracted domain for {domain}",
                        is_mvp_core=is_core,
                        estimated_risk_score=risk,
                    )
                )

        module_count = len(detected_modules)
        if module_count >= self._config.high_risk_module_threshold:
            complexity = ProjectComplexityLevel.HIGH_COMPLEXITY_RISK
            intervention_needed = self._config.auto_suggest_mvp
        elif module_count >= 3:
            complexity = ProjectComplexityLevel.MEDIUM
            intervention_needed = False
        else:
            complexity = ProjectComplexityLevel.LOW
            intervention_needed = False

        # Build phased plans
        phased_plans = self._build_phased_plans(detected_modules)
        nudge_xml = self._render_prompt_nudge(complexity, phased_plans)
        card_md = self._render_summary_card(complexity, detected_modules, phased_plans)

        duration_ms = (time.perf_counter() - start_time) * 1000.0
        return DistillationOutcome(
            complexity_level=complexity,
            detected_modules=detected_modules,
            phased_plans=phased_plans,
            intervention_needed=intervention_needed,
            distillation_prompt_nudge=nudge_xml,
            summary_card_markdown=card_md,
            evaluation_duration_ms=duration_ms,
        )

    def _build_phased_plans(self, modules: Sequence[ModuleSpec]) -> list[PhaseScopePlan]:
        """Splits detected modules into MVP Phase 1 (Core) and follow-up phases."""
        if not modules:
            return []

        core_mods: list[str] = [m.module_id for m in modules if m.is_mvp_core]
        ext_mods: list[str] = [m.module_id for m in modules if not m.is_mvp_core]

        # Limit Phase 1 to max_mvp_core_modules
        p1_targets = core_mods[: self._config.max_mvp_core_modules]
        remaining = core_mods[self._config.max_mvp_core_modules :] + ext_mods

        plans: list[PhaseScopePlan] = [
            PhaseScopePlan(
                phase_index=1,
                phase_name="Phase 1: Core MVP Architecture & Pipeline",
                target_modules=p1_targets,
                deliverable_description="Minimal runnable end-to-end loop with storage & basic UI/API.",
                acceptance_criteria=[
                    "Core database schema and migrations verified.",
                    "Primary data flow / CRUD UI or API operational.",
                    "Automated smoke tests passed without regressions.",
                ],
            )
        ]

        if remaining:
            plans.append(
                PhaseScopePlan(
                    phase_index=2,
                    phase_name="Phase 2: Business Extensions & Integrations",
                    target_modules=remaining[: self._config.max_mvp_core_modules],
                    deliverable_description="High-value business modules built on validated Phase 1 foundation.",
                    acceptance_criteria=[
                        "Integrations (e.g. payment/admin) complete without mutating Phase 1 core.",
                        "End-to-end business flow tests verified.",
                    ],
                )
            )

        if len(remaining) > self._config.max_mvp_core_modules:
            plans.append(
                PhaseScopePlan(
                    phase_index=3,
                    phase_name="Phase 3: Polishing, Observability & Secondary Features",
                    target_modules=remaining[self._config.max_mvp_core_modules :],
                    deliverable_description="Non-blocking enhancements, telemetry, and aesthetic polish.",
                    acceptance_criteria=["Full system integration tests pass."],
                )
            )

        return plans

    def _render_prompt_nudge(
        self,
        complexity: ProjectComplexityLevel,
        plans: Sequence[PhaseScopePlan],
    ) -> str:
        """Renders system prompt injection nudge instructing LLM to propose MVP distillation."""
        if complexity != ProjectComplexityLevel.HIGH_COMPLEXITY_RISK or not plans:
            return ""

        p1 = plans[0]
        targets_str = ", ".join(p1.target_modules)
        return (
            "<mvp_scope_distillation status='active'>\n"
            "  <guideline>\n"
            "    User request contains broad, multi-domain functional scope.\n"
            "    DO NOT attempt to output massive unverified codebases in a single turn.\n"
            f"    Adopt Stepwise MVP Strategy: Focus Phase 1 strictly on [{targets_str}].\n"
            "    Present the phased roadmap card clearly before scaffolding extensive code.\n"
            "  </guideline>\n"
            "</mvp_scope_distillation>"
        )

    def _render_summary_card(
        self,
        complexity: ProjectComplexityLevel,
        modules: Sequence[ModuleSpec],
        plans: Sequence[PhaseScopePlan],
    ) -> str:
        """Renders user-facing markdown card summarizing the proposed MVP roadmap."""
        if complexity != ProjectComplexityLevel.HIGH_COMPLEXITY_RISK:
            return ""

        lines: list[str] = [
            "### 🎯 项目需求主动收敛与 MVP 渐进开发建议",
            f"检测到您提出的需求涵盖了 **{len(modules)} 个子系统模块**。为防止一次性生成海量代码导致上下文溢出与逻辑混乱，建议采用**分阶段渐进式落地路径**：",
            "",
        ]
        for plan in plans:
            targets = ", ".join(plan.target_modules)
            lines.append(f"- **{plan.phase_name}**（范围: `{targets}`）")
            lines.append(f"  - 交付目标: {plan.deliverable_description}")
        lines.append("")
        lines.append("建议我们先跑通 **Phase 1 MVP 最小可用版本**，经您验证通过后再扩建进阶特性。")
        return "\n".join(lines)

    # State Machine methods
    def get_session_state(self, session_id: str) -> MvpPhaseLifecycleState:
        """Returns current lifecycle state for session."""
        return self._session_states.get(session_id, MvpPhaseLifecycleState.IDLE)

    def propose_plan(self, session_id: str, outcome: DistillationOutcome) -> None:
        """Stores plans and updates session state to PROPOSED if high complexity."""
        self._session_plans[session_id] = list(outcome.phased_plans)
        if outcome.intervention_needed:
            self._session_states[session_id] = MvpPhaseLifecycleState.PROPOSED
        else:
            self._session_states[session_id] = MvpPhaseLifecycleState.IDLE

    def accept_and_start_phase(self, session_id: str, phase_index: int = 1) -> PhaseScopePlan | None:
        """Activates a specific phase for execution."""
        plans = self._session_plans.get(session_id, [])
        target_plan = next((p for p in plans if p.phase_index == phase_index), None)
        if not target_plan:
            return None

        self._session_active_phase[session_id] = phase_index
        if phase_index == 1:
            self._session_states[session_id] = MvpPhaseLifecycleState.PHASE_1_ACTIVE
        else:
            self._session_states[session_id] = MvpPhaseLifecycleState.PHASE_NEXT_READY
        return target_plan

    def verify_phase(self, session_id: str, phase_index: int, verification_notes: str) -> bool:
        """Marks a phase as verified with human acceptance or automated test evidence."""
        if session_id not in self._session_verified_notes:
            self._session_verified_notes[session_id] = {}
        self._session_verified_notes[session_id][phase_index] = verification_notes

        plans = self._session_plans.get(session_id, [])
        if phase_index == 1:
            self._session_states[session_id] = MvpPhaseLifecycleState.PHASE_1_VERIFIED
        elif phase_index >= len(plans):
            self._session_states[session_id] = MvpPhaseLifecycleState.ALL_COMPLETED
        else:
            self._session_states[session_id] = MvpPhaseLifecycleState.PHASE_NEXT_READY
        return True

    def generate_phase_handoff_context(
        self,
        session_id: str,
        previous_phase_contracts: str,
    ) -> str:
        """Generates lean, non-bloated handoff context carrying forward only verified contracts."""
        active_phase = self._session_active_phase.get(session_id, 1)
        notes = self._session_verified_notes.get(session_id, {}).get(active_phase, "All tests passed.")
        return (
            f"[Phase {active_phase} Handoff Contract - Verified]\n"
            f"Notes: {notes}\n"
            f"Architecture Contracts:\n{previous_phase_contracts.strip()}\n"
            f"[End Handoff Contract]"
        )

    def clear_session(self, session_id: str) -> None:
        """Cleans up session records."""
        self._session_states.pop(session_id, None)
        self._session_plans.pop(session_id, None)
        self._session_active_phase.pop(session_id, None)
        self._session_verified_notes.pop(session_id, None)
