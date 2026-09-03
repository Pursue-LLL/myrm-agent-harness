"""Unit tests for Eval Search/Test Set Leakage Guard & Anti-Contamination Isolation."""

import pytest

from myrm_agent_harness.eval.leakage_guard import (
    LeakageAuditResult,
    ParetoGeneralizationVerdict,
    audit_proposer_prompt_for_leakage,
    evaluate_pareto_generalization,
    filter_search_cases_for_proposer,
    filter_trajectories_for_proposer,
    is_test_case_spec,
    partition_dataset_split,
)
from myrm_agent_harness.eval.protocols import EvalCase, EvalCaseSplit


def test_eval_case_split_defaults_and_properties():
    case_search = EvalCase(message="Regular search case")
    assert case_search.split == EvalCaseSplit.SEARCH
    assert case_search.is_search_set is True
    assert case_search.is_test_set is False

    case_test = EvalCase(message="Held out test", split=EvalCaseSplit.TEST)
    assert case_test.split == EvalCaseSplit.TEST
    assert case_test.is_search_set is False
    assert case_test.is_test_set is True

    case_hard = EvalCase(message="Hard subset test", split=EvalCaseSplit.HARDSUBSET)
    assert case_hard.is_test_set is True
    assert case_hard.is_search_set is False


def test_is_test_case_spec_various_inputs():
    assert is_test_case_spec({"split": "test"}) is True
    assert is_test_case_spec({"split": "TEST_SET"}) is True
    assert is_test_case_spec({"split": "hard_subset"}) is True
    assert is_test_case_spec({"metadata": {"split": "test"}}) is True
    assert is_test_case_spec({"split": "search"}) is False
    assert is_test_case_spec({"message": "no split tag"}) is False
    assert is_test_case_spec(EvalCase(message="test", split=EvalCaseSplit.TEST)) is True
    assert is_test_case_spec(EvalCase(message="search", split=EvalCaseSplit.SEARCH)) is False


def test_filter_search_cases_for_proposer():
    cases = [
        {"message": "case 1 (search)", "split": "search"},
        {"message": "case 2 (test)", "split": "test"},
        {"message": "case 3 (legacy untagged)"},
        {"message": "case 4 (hard subset)", "split": "hard_subset"},
        EvalCase(message="case 5 (EvalCase search)", split=EvalCaseSplit.SEARCH),
        EvalCase(message="case 6 (EvalCase test)", split=EvalCaseSplit.TEST),
    ]

    filtered = filter_search_cases_for_proposer(cases)
    assert len(filtered) == 3

    messages = [
        c.message if isinstance(c, EvalCase) else c["message"] for c in filtered
    ]
    assert messages == [
        "case 1 (search)",
        "case 3 (legacy untagged)",
        "case 5 (EvalCase search)",
    ]


def test_filter_trajectories_for_proposer():
    traces = [
        {"id": "t1", "split": "search", "error": "file not found"},
        {"id": "t2", "split": "test", "error": "assertion failed: target 42"},
        {"id": "t3", "metadata": {"split": "test"}, "error": "regex error"},
        {"id": "t4", "trace": "clean search execution"},
    ]
    filtered = filter_trajectories_for_proposer(traces)
    assert len(filtered) == 2
    assert [t["id"] for t in filtered] == ["t1", "t4"]


def test_audit_proposer_prompt_for_leakage():
    test_cases = [
        EvalCase(message="Extract secret token 'XYZ-9988-SECURE' exactly", split=EvalCaseSplit.TEST),
        EvalCase(message="Short msg", split=EvalCaseSplit.TEST),
    ]

    clean_prompt = "Please optimize the skill to handle general token extraction patterns."
    audit_clean = audit_proposer_prompt_for_leakage(clean_prompt, test_cases)
    assert audit_clean.has_leakage is False
    assert audit_clean.to_dict()["has_leakage"] is False

    leaked_prompt = (
        "Focus on this test input: Extract secret token 'XYZ-9988-SECURE' exactly and ensure pass."
    )
    audit_leaked = audit_proposer_prompt_for_leakage(leaked_prompt, test_cases)
    assert audit_leaked.has_leakage is True
    assert 0 in audit_leaked.leaked_case_indices
    assert len(audit_leaked.detected_snippets) == 1
    assert "XYZ-9988-SECURE" in audit_leaked.detected_snippets[0]


def test_partition_dataset_split():
    assert partition_dataset_split([]) == ([], [])

    small = ["c1", "c2", "c3"]
    # < 4 threshold: all stay in search
    s_small, t_small = partition_dataset_split(small, min_holdout_threshold=4)
    assert len(s_small) == 3
    assert len(t_small) == 0

    large = [f"case_{i}" for i in range(10)]
    s_large, t_large = partition_dataset_split(large, search_ratio=0.7)
    assert len(s_large) == 7
    assert len(t_large) == 3
    assert s_large == [f"case_{i}" for i in range(7)]
    assert t_large == [f"case_{i}" for i in range(7, 10)]


def test_evaluate_pareto_generalization():
    # Insufficient holdout
    assert evaluate_pareto_generalization(0.8, 0.9, None, None) == ParetoGeneralizationVerdict.INSUFFICIENT_HOLDOUT

    # Overfitting: search improves (+0.2), test regresses (-0.1)
    assert evaluate_pareto_generalization(
        baseline_search_rate=0.6,
        target_search_rate=0.8,
        baseline_test_rate=0.7,
        target_test_rate=0.6,
    ) == ParetoGeneralizationVerdict.OVERFITTING

    # Severe collapse
    assert evaluate_pareto_generalization(
        baseline_search_rate=0.6,
        target_search_rate=0.9,
        baseline_test_rate=0.8,
        target_test_rate=0.5,
    ) == ParetoGeneralizationVerdict.GENERALIZATION_COLLAPSE

    # Pareto optimal: both improve
    assert evaluate_pareto_generalization(
        baseline_search_rate=0.6,
        target_search_rate=0.8,
        baseline_test_rate=0.6,
        target_test_rate=0.8,
    ) == ParetoGeneralizationVerdict.PARETO_OPTIMAL

    # Dual regression
    assert evaluate_pareto_generalization(
        baseline_search_rate=0.7,
        target_search_rate=0.5,
        baseline_test_rate=0.7,
        target_test_rate=0.5,
    ) == ParetoGeneralizationVerdict.REGRESSION

    # Stable parity
    assert evaluate_pareto_generalization(
        baseline_search_rate=0.8,
        target_search_rate=0.81,
        baseline_test_rate=0.8,
        target_test_rate=0.81,
    ) == ParetoGeneralizationVerdict.STABLE_PARITY
