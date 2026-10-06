"""Comprehensive unit tests for Dynamic Working Set Rules and Architecture Entropy Draining."""

from __future__ import annotations

from myrm_agent_harness.runtime.context.entropy_draining_engine import (
    EntropyDrainingEngine,
)
from myrm_agent_harness.runtime.context.path_scoped_rule_matcher import (
    PathScopedRuleMatcher,
)
from myrm_agent_harness.runtime.context.rule_telemetry_ledger import (
    RuleTelemetryLedger,
)
from myrm_agent_harness.runtime.context.working_set_rules_types import (
    ActiveWorkingSet,
    PathScope,
    RuleItem,
    RuleSeverity,
    RuleTaskPhase,
)


def test_path_scoped_matching_include_and_exclude() -> None:
    """Verify rules are routed according to include and exclude glob patterns."""
    matcher = PathScopedRuleMatcher()

    python_rule = RuleItem(
        rule_id="py_rule",
        title="Python 3.12+ Standards",
        content="Use strict type hints and avoid Any.",
        scope=PathScope(include_patterns=["*.py", "src/**/*.py"], exclude_patterns=["legacy/*"]),
        applicable_phases={RuleTaskPhase.CODE},
    )

    test_rule = RuleItem(
        rule_id="test_rule",
        title="Pytest Conventions",
        content="Always write fast unit tests with pytest.",
        scope=PathScope(include_patterns=["tests/**/*.py", "test_*.py"]),
        applicable_phases={RuleTaskPhase.TEST, RuleTaskPhase.CODE},
    )

    # Scenario 1: editing regular python source file
    ws_src = ActiveWorkingSet(active_paths=["src/core/engine.py"], current_phase=RuleTaskPhase.CODE)
    matched_src = matcher.match_rules([python_rule, test_rule], ws_src)
    assert len(matched_src) == 1
    assert matched_src[0].rule_id == "py_rule"

    # Scenario 2: editing legacy excluded file
    ws_legacy = ActiveWorkingSet(active_paths=["legacy/old_parser.py"], current_phase=RuleTaskPhase.CODE)
    matched_legacy = matcher.match_rules([python_rule, test_rule], ws_legacy)
    assert len(matched_legacy) == 0

    # Scenario 3: editing test file
    ws_test = ActiveWorkingSet(active_paths=["tests/unit/test_engine.py"], current_phase=RuleTaskPhase.TEST)
    matched_test = matcher.match_rules([python_rule, test_rule], ws_test)
    assert len(matched_test) == 1
    assert matched_test[0].rule_id == "test_rule"


def test_task_phase_filtering() -> None:
    """Verify rules with restricted phases do not trigger during irrelevant task stages."""
    matcher = PathScopedRuleMatcher()

    spec_only_rule = RuleItem(
        rule_id="spec_rfc",
        title="RFC Spec Gate",
        content="Ensure RFC requirements are thoroughly drafted before code.",
        scope=PathScope(include_patterns=["*"]),
        applicable_phases={RuleTaskPhase.SPEC, RuleTaskPhase.PLAN},
    )

    ws_plan = ActiveWorkingSet(active_paths=["design.md"], current_phase=RuleTaskPhase.PLAN)
    matched_plan = matcher.match_rules([spec_only_rule], ws_plan)
    assert len(matched_plan) == 1

    ws_code = ActiveWorkingSet(active_paths=["main.py"], current_phase=RuleTaskPhase.CODE)
    matched_code = matcher.match_rules([spec_only_rule], ws_code)
    assert len(matched_code) == 0


def test_conflict_resolution_by_severity() -> None:
    """Verify clashing rules sharing conflict_keys are resolved deterministically by severity."""
    engine = EntropyDrainingEngine()

    rule_mandatory = RuleItem(
        rule_id="strict_double_quotes",
        title="Double Quotes Policy",
        content="All strings must use double quotes.",
        scope=PathScope(include_patterns=["*"]),
        severity=RuleSeverity.MANDATORY,
        conflict_keys={"code_quote_convention"},
    )

    rule_advisory = RuleItem(
        rule_id="optional_single_quotes",
        title="Single Quotes Suggestion",
        content="Prefer single quotes for short identifiers.",
        scope=PathScope(include_patterns=["*"]),
        severity=RuleSeverity.ADVISORY,
        conflict_keys={"code_quote_convention"},
    )

    engine.register_rules([rule_mandatory, rule_advisory])

    ws = ActiveWorkingSet(active_paths=["app.py"], current_phase=RuleTaskPhase.CODE)
    resolved = engine.get_pruned_working_set_rules(ws)

    assert len(resolved) == 1
    assert resolved[0].rule_id == "strict_double_quotes"
    assert resolved[0].severity == RuleSeverity.MANDATORY


def test_rule_telemetry_hits_and_dilution() -> None:
    """Verify telemetry ledger records matches and calculates avoided dilution ratio."""
    ledger = RuleTelemetryLedger()
    ledger.record_match("rule_a", RuleTaskPhase.CODE, "src/api.py")
    ledger.record_match("rule_a", RuleTaskPhase.CODE, "src/api.py")
    ledger.record_match("rule_b", RuleTaskPhase.TEST, "tests/test_api.py")

    rec_a = ledger.get_record("rule_a")
    assert rec_a is not None
    assert rec_a.hits_count == 2
    assert "src/api.py" in rec_a.matched_paths

    # Dilution avoided calculation: out of 50 total rules, only 2 matched -> 96% pollution prevented
    dilution_ratio = ledger.compute_dilution_ratio(total_available_rules=50, matched_rules_count=2)
    assert dilution_ratio == 0.96


def test_entropy_draining_stale_rules_archival() -> None:
    """Verify architecture entropy sweep archives unactivated rules and surfaces conflicts."""
    engine = EntropyDrainingEngine()

    active_rule = RuleItem(
        rule_id="active_r",
        title="Active Rule",
        content="Actively utilized constraint.",
        scope=PathScope(include_patterns=["*"]),
    )

    stale_rule_1 = RuleItem(
        rule_id="stale_r1",
        title="Obsolete Protocol 2024",
        content="Deprecated protocol guideline that is never matched.",
        scope=PathScope(include_patterns=["obsolete/**"]),
    )

    engine.register_rules([active_rule, stale_rule_1])

    # Trigger active rule once
    engine.get_pruned_working_set_rules(ActiveWorkingSet(active_paths=["main.py"], current_phase=RuleTaskPhase.CODE))

    # Run entropy draining sweep
    report = engine.drain_entropy(min_inactivity_threshold=0)

    assert report.total_rules_inspected == 2
    assert "stale_r1" in report.stale_rules_archived
    assert report.active_rules_retained == 1

    # Subsequent fetch should not include archived stale rule
    all_rules = engine.get_pruned_working_set_rules(
        ActiveWorkingSet(active_paths=["obsolete/code.py"], current_phase=RuleTaskPhase.CODE)
    )
    assert len(all_rules) == 1
    assert all_rules[0].rule_id == "active_r"


def test_xml_prompt_rendering() -> None:
    """Verify pruned rules are serialized to clean XML blocks for LLM system prompts."""
    engine = EntropyDrainingEngine()

    rule = RuleItem(
        rule_id="no_any",
        title="Zero Any Type Redline",
        content="Never emit Any in Python code.",
        severity=RuleSeverity.MANDATORY,
    )

    xml_output = engine.render_rules_prompt_xml([rule])
    assert "<dynamic_working_set_rules>" in xml_output
    assert '<rule id="no_any" severity="mandatory">' in xml_output
    assert "<title>Zero Any Type Redline</title>" in xml_output
    assert "<content>Never emit Any in Python code.</content>" in xml_output
    assert "</dynamic_working_set_rules>" in xml_output
