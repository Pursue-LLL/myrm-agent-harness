"""Tests for Financial Sandplay Simulation and Skill Solidification Suite (Item 235)."""

import pytest

from myrm_agent_harness.agent.context_management.sandplay_simulation import (
    CausalityEdge,
    CausalityNode,
    CausalityTier,
    FinancialSandplaySimulationEngine,
    ImpactDirection,
    IndustryChainGraph,
    SandplaySimulationResult,
    SolidifiedSkillPackage,
)


def test_financial_sandplay_four_tier_simulation() -> None:
    """Verify 4-tier causality network generation (Macro Policy -> Topology -> Valuation -> Reverse Stress)."""
    engine = FinancialSandplaySimulationEngine()

    macro_event = "State Council releases National Humanoid Robotics Action Plan 2026"
    industry_focus = "Humanoid Robotics & Embodied AI Value Chain"

    result = engine.simulate_event_causality(
        macro_event=macro_event,
        industry_focus=industry_focus,
    )

    assert result.macro_event == macro_event
    assert result.industry_focus == industry_focus
    assert result.stress_test_passed

    graph = result.industry_graph
    assert len(graph.nodes) >= 6
    assert len(graph.edges) >= 4

    # Verify all 4 tiers exist in nodes
    tiers_present = {n.tier for n in graph.nodes}
    assert CausalityTier.TIER_1_MACRO_POLICY in tiers_present
    assert CausalityTier.TIER_2_INDUSTRY_TOPOLOGY in tiers_present
    assert CausalityTier.TIER_3_TICKER_VALUATION in tiers_present
    assert CausalityTier.TIER_4_REVERSE_STRESS_TEST in tiers_present

    # Tier 1 Macro Policy Node assertions
    t1_nodes = [n for n in graph.nodes if n.tier == CausalityTier.TIER_1_MACRO_POLICY]
    assert len(t1_nodes) >= 1
    assert t1_nodes[0].impact_score > 0.8
    assert t1_nodes[0].direction == ImpactDirection.POSITIVE_TAILWIND

    # Tier 3 Ticker Valuation Node assertions
    t3_nodes = [n for n in graph.nodes if n.tier == CausalityTier.TIER_3_TICKER_VALUATION]
    assert len(t3_nodes) >= 2
    assert "pe_sensitivity" in t3_nodes[0].metrics
    assert t3_nodes[0].metrics["revenue_elasticity"] > 0.3

    # Tier 4 Reverse Stress Test Node assertions
    t4_nodes = [n for n in graph.nodes if n.tier == CausalityTier.TIER_4_REVERSE_STRESS_TEST]
    assert len(t4_nodes) >= 1
    assert t4_nodes[0].impact_score < 0.0
    assert t4_nodes[0].direction == ImpactDirection.NEGATIVE_HEADWIND

    # Ticker sensitivities matrix
    assert "688XXX.SH" in graph.ticker_sensitivities
    assert graph.ticker_sensitivities["688XXX.SH"] > 0.3


def test_causality_artifact_anchoring() -> None:
    """Verify causality deduction graph freezes into an immutable context sanctuary anchor."""
    engine = FinancialSandplaySimulationEngine()

    result = engine.simulate_event_causality(
        macro_event="Semiconductor subsidy expansion",
        industry_focus="Advanced Packaging",
    )

    anchor_msg = engine.anchor_causality_artifact(result)

    assert anchor_msg["role"] == "system"
    assert anchor_msg["name"] == "knowledge_sanctuary_anchor"
    assert result.anchored_artifact_id in anchor_msg["content"]
    assert "4-Tier Causality Deductions" in anchor_msg["content"]
    assert "Transmission Mechanisms" in anchor_msg["content"]
    assert "Ticker Valuation Sensitivities" in anchor_msg["content"]
    assert "Guaranteed Retention" in anchor_msg["content"]


def test_solidify_to_reusable_skill_package() -> None:
    """Verify continuous sandplay workflow solidifies into standardized, deployable SKILL.md package."""
    engine = FinancialSandplaySimulationEngine()

    result = engine.simulate_event_causality(
        macro_event="Low-Altitude Economy Airspace Deregulation",
        industry_focus="eVTOL & Airborne Avionics",
    )

    skill_pkg = engine.solidify_to_skill(
        result=result,
        skill_name="eVTOL Industrial Sandplay Analyst",
        author="Myrm Quant Architect",
    )

    assert skill_pkg.skill_name == "eVTOL Industrial Sandplay Analyst"
    assert skill_pkg.skill_slug == "evtol-industrial-sandplay-analyst"
    assert "Low-Altitude Economy Airspace Deregulation" in skill_pkg.skill_markdown_content

    md_content = skill_pkg.skill_markdown_content

    # Frontmatter assertions
    assert "---" in md_content
    assert "category: financial_sandplay" in md_content
    assert "author: Myrm Quant Architect" in md_content

    # Mermaid diagram assertions
    assert "```mermaid" in md_content
    assert "graph TD" in md_content
    assert "node_t1_policy" in md_content

    # Execution code template assertions
    assert "```python" in md_content
    assert "def evaluate_industry_elasticity" in md_content
