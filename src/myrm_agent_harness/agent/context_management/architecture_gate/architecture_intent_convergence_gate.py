"""Core implementation of Architecture Planning Discussion-First and Intent Convergence Gate.

Enforces discussion-first advisory mode on high-complexity requirements, suppresses
destructive write tools prior to user consent, produces multi-option trade-off matrices,
and governs transition into execution-locked mode upon blueprint approval.
"""

from __future__ import annotations

import threading
import time
import uuid

from .architecture_gate_types import (
    ArchitectureMode,
    ExecutionBlueprint,
    ExecutionBlueprintStep,
    GateEvaluationResult,
    TechnologyOption,
    TradeoffMatrix,
)


class ArchitectureIntentConvergenceGate:
    """Industrial gateway governing architecture planning and intent convergence gates."""

    HIGH_RISK_TRIGGER_KEYWORDS: tuple[str, ...] = (
        "架构",
        "选型",
        "重构",
        "编辑器",
        "迁移",
        "数据库",
        "框架",
        "architecture",
        "tradeoff",
        "refactor",
        "editor",
        "migration",
        "stack selection",
    )

    DESTRUCTIVE_TOOLS: frozenset[str] = frozenset({
        "write_file",
        "write_to_file",
        "replace_file_content",
        "execute_destructive_command",
        "run_bash_write",
        "git_commit",
    })

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._modes: dict[str, ArchitectureMode] = {}
        self._matrices: dict[str, TradeoffMatrix] = {}
        self._blueprints: dict[str, ExecutionBlueprint] = {}

    def get_mode(self, session_id: str) -> ArchitectureMode:
        """Get the current architecture mode for a session."""
        with self._lock:
            return self._modes.get(session_id, ArchitectureMode.DISCUSSION_ADVISORY)

    def evaluate_requirement(self, session_id: str, prompt: str) -> bool:
        """Inspect prompt for high-risk architectural intent and engage advisory mode."""
        lower_prompt = prompt.lower()
        matched = any(kw in lower_prompt for kw in self.HIGH_RISK_TRIGGER_KEYWORDS)

        with self._lock:
            current_mode = self._modes.get(session_id)
            if current_mode == ArchitectureMode.EXECUTION_LOCKED:
                return False  # Already approved and locked

            if matched:
                self._modes[session_id] = ArchitectureMode.DISCUSSION_ADVISORY
                return True
            return False

    def create_tradeoff_matrix(
        self,
        session_id: str,
        problem_statement: str,
        options: list[TechnologyOption],
        recommended_id: str,
        rationale: str,
    ) -> TradeoffMatrix:
        """Register a multi-option trade-off matrix for the session."""
        if not options:
            raise ValueError("Trade-off matrix requires at least one option.")

        matrix = TradeoffMatrix(
            matrix_id=f"matrix-{uuid.uuid4().hex[:8]}",
            problem_statement=problem_statement,
            options=tuple(options),
            recommended_option_id=recommended_id,
            recommendation_rationale=rationale,
        )

        with self._lock:
            self._matrices[session_id] = matrix
            self._modes[session_id] = ArchitectureMode.DISCUSSION_ADVISORY

        return matrix

    def generate_execution_blueprint(
        self,
        session_id: str,
        selected_option_id: str,
        title: str,
        steps: list[ExecutionBlueprintStep],
    ) -> ExecutionBlueprint:
        """Create structured execution blueprint, advancing mode to INTENT_CONVERGING."""
        if not steps:
            raise ValueError("Execution blueprint requires at least one implementation step.")

        blueprint = ExecutionBlueprint(
            blueprint_id=f"blueprint-{uuid.uuid4().hex[:8]}",
            selected_option_id=selected_option_id,
            title=title,
            steps=tuple(steps),
            is_approved_by_user=False,
            approved_at=None,
        )

        with self._lock:
            self._blueprints[session_id] = blueprint
            self._modes[session_id] = ArchitectureMode.INTENT_CONVERGING

        return blueprint

    def approve_and_lock_plan(
        self, session_id: str, blueprint_id: str
    ) -> GateEvaluationResult:
        """Record explicit user approval, unlocking execution tools and freezing plan."""
        with self._lock:
            blueprint = self._blueprints.get(session_id)
            if not blueprint or blueprint.blueprint_id != blueprint_id:
                raise ValueError(f"No active blueprint found with id: {blueprint_id}")

            approved_blueprint = ExecutionBlueprint(
                blueprint_id=blueprint.blueprint_id,
                selected_option_id=blueprint.selected_option_id,
                title=blueprint.title,
                steps=blueprint.steps,
                is_approved_by_user=True,
                approved_at=time.time(),
            )
            self._blueprints[session_id] = approved_blueprint
            self._modes[session_id] = ArchitectureMode.EXECUTION_LOCKED

        return self.get_evaluation_result(session_id)

    def is_tool_allowed(self, session_id: str, tool_name: str) -> tuple[bool, str]:
        """Verify whether a tool execution is permitted under current architecture gate."""
        with self._lock:
            mode = self._modes.get(session_id, ArchitectureMode.DISCUSSION_ADVISORY)

        if mode in (ArchitectureMode.DISCUSSION_ADVISORY, ArchitectureMode.INTENT_CONVERGING):
            if tool_name in self.DESTRUCTIVE_TOOLS:
                return (
                    False,
                    "⚠️ 当前处于架构研讨与意图收敛门禁态，写操作已被硬护栏抑制。请先完成技术选型讨论与蓝图批准。",
                )

        return True, "Tool execution permitted."

    def render_interactive_convergence_card(self, session_id: str) -> str:
        """Render a structured XML interactive convergence card for UI display."""
        with self._lock:
            matrix = self._matrices.get(session_id)
            blueprint = self._blueprints.get(session_id)
            mode = self._modes.get(session_id, ArchitectureMode.DISCUSSION_ADVISORY)

        lines: list[str] = [
            "<intent_convergence_card>",
            f"  <status mode='{mode.value}' />",
        ]

        if matrix:
            lines.append(f"  <problem>{matrix.problem_statement}</problem>")
            lines.append("  <options>")
            for opt in matrix.options:
                rec_attr = " recommended='true'" if opt.is_recommended else ""
                lines.append(f"    <option id='{opt.option_id}' name='{opt.name}'{rec_attr}>")
                lines.append(f"      <summary>{opt.summary}</summary>")
                lines.append(f"      <complexity>{opt.complexity_score}/10</complexity>")
                lines.append(f"      <performance>{opt.performance_score}/10</performance>")
                lines.append("    </option>")
            lines.append("  </options>")
            lines.append(f"  <recommendation id='{matrix.recommended_option_id}'>{matrix.recommendation_rationale}</recommendation>")

        if blueprint:
            approved_attr = "true" if blueprint.is_approved_by_user else "false"
            lines.append(f"  <blueprint id='{blueprint.blueprint_id}' approved='{approved_attr}'>")
            lines.append(f"    <title>{blueprint.title}</title>")
            lines.append("    <steps>")
            for step in blueprint.steps:
                lines.append(f"      <step order='{step.order}' title='{step.title}'>{step.description}</step>")
            lines.append("    </steps>")
            lines.append("  </blueprint>")

        lines.append("</intent_convergence_card>")
        return "\n".join(lines)

    def get_evaluation_result(self, session_id: str) -> GateEvaluationResult:
        """Produce the aggregate snapshot of current gate state."""
        with self._lock:
            mode = self._modes.get(session_id, ArchitectureMode.DISCUSSION_ADVISORY)
            matrix = self._matrices.get(session_id)
            blueprint = self._blueprints.get(session_id)

        suppressed = mode in (
            ArchitectureMode.DISCUSSION_ADVISORY,
            ArchitectureMode.INTENT_CONVERGING,
        )
        prompt = (
            "Ready for execution."
            if mode == ArchitectureMode.EXECUTION_LOCKED
            else "Awaiting architecture convergence and user approval."
        )

        return GateEvaluationResult(
            session_id=session_id,
            current_mode=mode,
            destructive_tools_suppressed=suppressed,
            active_matrix=matrix,
            active_blueprint=blueprint,
            convergence_prompt=prompt,
        )
