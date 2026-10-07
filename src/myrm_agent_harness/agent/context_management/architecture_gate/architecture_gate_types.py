"""Type definitions for Architecture Planning Discussion-First and Intent Convergence Gate.

Provides immutable data contracts for adaptive discussion modes, technology trade-off
matrices, execution blueprint step sequences, and intent convergence gates.

[INPUT]
- None (self-contained; standard library only)

[OUTPUT]
- ArchitectureMode: Lifecycle mode governing tool suppression and advisory gates.
- TechnologyOption: A viable architectural or technology option with trade-off dimensions.
- TradeoffMatrix: Multi-option trade-off decision matrix comparing architectural routes.
- ExecutionBlueprintStep: A discrete, verifiable implementation step within an approved blueprint.
- ExecutionBlueprint: Structured implementation blueprint ready for user convergence and locking.
- GateEvaluationResult: Snapshot of current session architecture mode, tool gates, and active artifacts.

[POS]
Type definitions for Architecture Planning Discussion-First and Intent Convergence Gate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class ArchitectureMode(str, Enum):
    """Lifecycle mode governing tool suppression and advisory gates."""

    DISCUSSION_ADVISORY = "DISCUSSION_ADVISORY"
    INTENT_CONVERGING = "INTENT_CONVERGING"
    EXECUTION_LOCKED = "EXECUTION_LOCKED"


@dataclass(frozen=True)
class TechnologyOption:
    """A viable architectural or technology option with trade-off dimensions."""

    option_id: str
    name: str
    summary: str
    pros: tuple[str, ...]
    cons: tuple[str, ...]
    complexity_score: int  # 1 (simple) to 10 (very complex)
    performance_score: int  # 1 (poor) to 10 (exceptional)
    is_recommended: bool = False


@dataclass(frozen=True)
class TradeoffMatrix:
    """Multi-option trade-off decision matrix comparing architectural routes."""

    matrix_id: str
    problem_statement: str
    options: tuple[TechnologyOption, ...]
    recommended_option_id: str
    recommendation_rationale: str


@dataclass(frozen=True)
class ExecutionBlueprintStep:
    """A discrete, verifiable implementation step within an approved blueprint."""

    step_id: str
    order: int
    title: str
    description: str
    acceptance_criteria: tuple[str, ...]
    affected_components: tuple[str, ...]


@dataclass(frozen=True)
class ExecutionBlueprint:
    """Structured implementation blueprint ready for user convergence and locking."""

    blueprint_id: str
    selected_option_id: str
    title: str
    steps: tuple[ExecutionBlueprintStep, ...]
    is_approved_by_user: bool = False
    approved_at: float | None = None


@dataclass(frozen=True)
class GateEvaluationResult:
    """Snapshot of current session architecture mode, tool gates, and active artifacts."""

    session_id: str
    current_mode: ArchitectureMode
    destructive_tools_suppressed: bool
    active_matrix: TradeoffMatrix | None
    active_blueprint: ExecutionBlueprint | None
    convergence_prompt: str
