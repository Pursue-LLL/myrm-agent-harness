"""Type contracts and definitions for Financial Sandplay Simulation and Skill Solidification Suite.

Defines four-tier causality graphs, valuation sensitivity matrices,
sandplay simulation results, and solidified skill package specifications.

[INPUT]
- None (self-contained; standard library only)

[OUTPUT]
- CausalityTier: Four-tier hierarchy of financial industrial chain causality deduction.
- ImpactDirection: Net directional impact of a causality node on valuation or earnings.
- CausalityNode: An analytical entity or state in the sandplay causality network.
- CausalityEdge: A directed causal transmission mechanism connecting two nodes.
- IndustryChainGraph: Topological graph representing the complete four-tier deduction tree.
- SandplaySimulationResult: Synthesized outcome of continuous sandplay deduction and sandbox valuation.
- SolidifiedSkillPackage: Ready-to-deploy SKILL.md specification solidified from a successful simulation run.

[POS]
Type contracts and definitions for Financial Sandplay Simulation and Skill Solidification Suite.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import time


class CausalityTier(StrEnum):
    """Four-tier hierarchy of financial industrial chain causality deduction."""

    TIER_1_MACRO_POLICY = "tier_1_macro_policy"  # Monetary, fiscal, and regulatory transmission
    TIER_2_INDUSTRY_TOPOLOGY = "tier_2_industry_topology"  # Upstream, midstream, downstream sectors
    TIER_3_TICKER_VALUATION = "tier_3_ticker_valuation"  # Stock targets, EPS elasticity, multiple expansion
    TIER_4_REVERSE_STRESS_TEST = "tier_4_reverse_stress_test"  # Adverse shocks, margin compression, patent risks


class ImpactDirection(StrEnum):
    """Net directional impact of a causality node on valuation or earnings."""

    POSITIVE_TAILWIND = "positive_tailwind"  # Beneficial driver (+)
    NEGATIVE_HEADWIND = "negative_headwind"  # Detrimental friction (-)
    NEUTRAL_AMBIGUOUS = "neutral_ambiguous"  # Ambiguous or balanced (=)


@dataclass(frozen=True)
class CausalityNode:
    """An analytical entity or state in the sandplay causality network."""

    node_id: str
    tier: CausalityTier
    label: str
    impact_score: float  # Normalized between -1.0 (severe drag) and +1.0 (massive tailwind)
    direction: ImpactDirection
    summary: str
    metrics: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class CausalityEdge:
    """A directed causal transmission mechanism connecting two nodes."""

    source_id: str
    target_id: str
    mechanism: str
    transmission_weight: float  # Sensitivity weight from 0.0 to 1.0


@dataclass(frozen=True)
class IndustryChainGraph:
    """Topological graph representing the complete four-tier deduction tree."""

    macro_event: str
    industry_focus: str
    nodes: list[CausalityNode]
    edges: list[CausalityEdge]
    ticker_sensitivities: dict[str, float]


@dataclass(frozen=True)
class SandplaySimulationResult:
    """Synthesized outcome of continuous sandplay deduction and sandbox valuation."""

    event_id: str
    macro_event: str
    industry_focus: str
    industry_graph: IndustryChainGraph
    stress_test_passed: bool
    anchored_artifact_id: str
    simulated_at: float = field(default_factory=time.time)


@dataclass(frozen=True)
class SolidifiedSkillPackage:
    """Ready-to-deploy SKILL.md specification solidified from a successful simulation run."""

    skill_name: str
    skill_slug: str
    description: str
    skill_markdown_content: str
    created_at: float = field(default_factory=time.time)
