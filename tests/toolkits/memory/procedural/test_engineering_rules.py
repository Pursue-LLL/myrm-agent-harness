"""Unit tests for Domain Engineering Procedural Memory and Skill Workflow Engine."""

from datetime import UTC, datetime

import pytest

from myrm_agent_harness.toolkits.memory.procedural import (
    ConstraintBoundary,
    DomainEngineeringProceduralEngine,
    EngineeringPreflightViolationError,
    EngineeringProceduralRule,
    EngineeringRuleCompilerAndEvaluator,
    EngineeringRuleSeverity,
)


@pytest.fixture
def evaluator() -> EngineeringRuleCompilerAndEvaluator:
    """Fixture providing engineering rule evaluator."""
    return EngineeringRuleCompilerAndEvaluator()


@pytest.fixture
def sample_drc_rule() -> EngineeringProceduralRule:
    """Fixture providing a standard PCB DRC trace width rule."""
    return EngineeringProceduralRule(
        rule_id="pcb_drc_min_trace_width",
        domain="pcb_drc",
        version="1.0.0",
        parameter_name="trace_width_mm",
        boundary=ConstraintBoundary(min_value=0.15, max_value=2.0, unit="mm"),
        description="Standard 1oz copper minimum trace width to prevent etching breaks.",
        severity=EngineeringRuleSeverity.ERROR,
        created_at=datetime.now(UTC),
    )


def test_evaluator_numeric_bounds(
    evaluator: EngineeringRuleCompilerAndEvaluator,
    sample_drc_rule: EngineeringProceduralRule,
) -> None:
    """Test numeric boundaries evaluation for underflow, overflow, and nominal values."""
    # 1. Underflow check
    res_under = evaluator.evaluate_rule(sample_drc_rule, 0.10)
    assert res_under.passed is False
    assert res_under.severity == EngineeringRuleSeverity.ERROR
    assert res_under.suggested_value == 0.15
    assert "below physical manufacturing threshold" in (res_under.violation_message or "")

    # 2. Overflow check
    res_over = evaluator.evaluate_rule(sample_drc_rule, 3.5)
    assert res_over.passed is False
    assert res_over.severity == EngineeringRuleSeverity.ERROR
    assert res_over.suggested_value == 2.0
    assert "exceeds maximum manufacturing tolerance" in (res_over.violation_message or "")

    # 3. Nominal valid check
    res_valid = evaluator.evaluate_rule(sample_drc_rule, 0.25)
    assert res_valid.passed is True
    assert res_valid.violation_message is None
    assert res_valid.suggested_value is None


def test_evaluator_categorical_bounds(evaluator: EngineeringRuleCompilerAndEvaluator) -> None:
    """Test discrete categorical allowable values."""
    layer_rule = EngineeringProceduralRule(
        rule_id="pcb_layer_stack_material",
        domain="pcb_drc",
        version="1.0.0",
        parameter_name="substrate_material",
        boundary=ConstraintBoundary(allowed_values=["FR4", "Rogers_4350B", "Polyimide"]),
        description="Allowed core dielectric materials.",
        severity=EngineeringRuleSeverity.ERROR,
        created_at=datetime.now(UTC),
    )

    # Valid material
    res_ok = evaluator.evaluate_rule(layer_rule, "FR4")
    assert res_ok.passed is True

    # Invalid material
    res_bad = evaluator.evaluate_rule(layer_rule, "Cardboard")
    assert res_bad.passed is False
    assert res_bad.suggested_value == "FR4"
    assert "violates permissible set" in (res_bad.violation_message or "")


def test_evaluator_missing_parameter(
    evaluator: EngineeringRuleCompilerAndEvaluator,
    sample_drc_rule: EngineeringProceduralRule,
) -> None:
    """Test detection of missing design parameter."""
    res_missing = evaluator.evaluate_rule(sample_drc_rule, None)
    assert res_missing.passed is False
    assert "is missing from design specification" in (res_missing.violation_message or "")
    assert res_missing.suggested_value == 0.15


def test_engine_progressive_disclosure() -> None:
    """Test domain and context tag filtering for progressive rule assembly."""
    engine = DomainEngineeringProceduralEngine()
    now = datetime.now(UTC)

    # General PCB rule
    engine.register_rule(
        EngineeringProceduralRule(
            rule_id="pcb_board_thickness",
            domain="pcb_drc",
            version="1.0.0",
            parameter_name="board_thickness_mm",
            boundary=ConstraintBoundary(min_value=0.8, max_value=3.2, unit="mm"),
            description="Overall board thickness",
            created_at=now,
        )
    )

    # Specialized High-Frequency RF rule (requires tag 'rf_microwave')
    engine.register_rule(
        EngineeringProceduralRule(
            rule_id="pcb_rf_dielectric_loss",
            domain="pcb_drc",
            version="1.0.0",
            parameter_name="dielectric_loss_tangent",
            boundary=ConstraintBoundary(max_value=0.004),
            description="RF loss tangent limit",
            precondition_tags=["rf_microwave"],
            created_at=now,
        )
    )

    # Unrelated mechanical rule (domain 'mechanical_cad')
    engine.register_rule(
        EngineeringProceduralRule(
            rule_id="mech_enclosure_clearance",
            domain="mechanical_cad",
            version="1.0.0",
            parameter_name="clearance_mm",
            boundary=ConstraintBoundary(min_value=1.0),
            description="Chassis clearance",
            created_at=now,
        )
    )

    # Case 1: Standard PCB task without RF tags
    standard_rules = engine.assemble_rules_for_context("pcb_drc")
    assert len(standard_rules) == 1
    assert standard_rules[0].rule_id == "pcb_board_thickness"

    # Case 2: RF PCB task with matching tag
    rf_rules = engine.assemble_rules_for_context("pcb_drc", active_tags=["rf_microwave"])
    assert len(rf_rules) == 2
    rule_ids = {r.rule_id for r in rf_rules}
    assert rule_ids == {"pcb_board_thickness", "pcb_rf_dielectric_loss"}

    # Case 3: Mechanical CAD domain
    mech_rules = engine.assemble_rules_for_context("mechanical_cad")
    assert len(mech_rules) == 1
    assert mech_rules[0].rule_id == "mech_enclosure_clearance"


def test_engine_rule_versioning_and_rollback() -> None:
    """Test registering multiple versions of an engineering rule, switching, and rollback."""
    engine = DomainEngineeringProceduralEngine()
    now = datetime.now(UTC)

    # Version 1: relaxed clearance (min 0.20 mm)
    v1 = EngineeringProceduralRule(
        rule_id="clearance_rule",
        domain="pcb_drc",
        version="1.0.0",
        parameter_name="clearance_mm",
        boundary=ConstraintBoundary(min_value=0.20, unit="mm"),
        description="Standard legacy process clearance",
        created_at=now,
    )
    # Version 2: strict HDI micro-via clearance (min 0.075 mm)
    v2 = EngineeringProceduralRule(
        rule_id="clearance_rule",
        domain="pcb_drc",
        version="2.0.0-hdi",
        parameter_name="clearance_mm",
        boundary=ConstraintBoundary(min_value=0.075, unit="mm"),
        description="High-density interconnect clearance",
        created_at=now,
    )

    engine.register_rule(v1)
    assert engine.get_active_rule("clearance_rule") is not None
    assert engine.get_active_rule("clearance_rule").version == "1.0.0"

    # Register v2 and activate it
    engine.register_rule(v2, activate=True)
    assert engine.get_active_rule("clearance_rule").version == "2.0.0-hdi"

    # 0.10 mm fails v1 (min 0.20) but passes v2 (min 0.075)
    params = {"clearance_mm": 0.10}
    rep_v2 = engine.preflight_check("pcb_drc", params)
    assert rep_v2.passed is True

    # Roll back to v1
    engine.switch_rule_version("clearance_rule", "1.0.0")
    assert engine.get_active_rule("clearance_rule").version == "1.0.0"

    rep_v1 = engine.preflight_check("pcb_drc", params)
    assert rep_v1.passed is False
    assert len(rep_v1.violations) == 1
    assert rep_v1.recommended_fixes["clearance_mm"] == 0.20


def test_enforce_preflight_gate_blocking(sample_drc_rule: EngineeringProceduralRule) -> None:
    """Test gate enforcement throws exception when blocking rules fail."""
    engine = DomainEngineeringProceduralEngine()
    engine.register_rule(sample_drc_rule)

    # Compliant design
    ok_report = engine.enforce_preflight_gate("pcb_drc", {"trace_width_mm": 0.30})
    assert ok_report.passed is True

    # Breaching design
    with pytest.raises(EngineeringPreflightViolationError) as exc_info:
        engine.enforce_preflight_gate("pcb_drc", {"trace_width_mm": 0.05})

    err = exc_info.value
    assert len(err.report.violations) == 1
    assert err.report.violations[0].rule_id == "pcb_drc_min_trace_width"


def test_auto_remediation_pipeline(sample_drc_rule: EngineeringProceduralRule) -> None:
    """Test automatic patching of design parameters to meet manufacturing rules."""
    engine = DomainEngineeringProceduralEngine()
    engine.register_rule(sample_drc_rule)

    suboptimal_design = {"trace_width_mm": 0.05, "component_count": 42}
    fixed_design = engine.auto_remediate_parameters("pcb_drc", suboptimal_design)

    # trace_width_mm should be patched to the min acceptable boundary (0.15)
    assert fixed_design["trace_width_mm"] == 0.15
    assert fixed_design["component_count"] == 42

    # Fixed design passes preflight check
    report = engine.enforce_preflight_gate("pcb_drc", fixed_design)
    assert report.passed is True
