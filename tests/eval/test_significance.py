"""Tests for paired statistical significance and plateau diagnosis engine.

[INPUT]
- pytest (POS: testing framework)
- myrm_agent_harness.eval.significance (POS: significance engine under test)
- myrm_agent_harness.eval.plateau (POS: plateau diagnosis under test)
- myrm_agent_harness.eval.matrix (POS: cross-profile comparative matrix result)
- myrm_agent_harness.eval.protocols (POS: evaluation protocol data structures)

[OUTPUT]
- TestSignificanceMath: verification of exact binomial and Chi2 p-values
- TestPairedSignificanceAssessment: verification of McNemar, Bootstrap CI, and Plateau
- TestPlateauDiagnosisMechanisms: verification of canonical 4 Meta-Harness mechanisms
- TestMatrixResultSignificanceIntegration: verification of MatrixResult property & serialization

[POS]
Complete unit test suite for paired statistical hypothesis testing, continuous
resource deltas, plateau diagnostics, and Matrix eval integration.
"""

from __future__ import annotations

import math

from myrm_agent_harness.eval.matrix import MatrixResult
from myrm_agent_harness.eval.plateau import (
    PlateauMechanism,
    diagnose_plateau,
)
from myrm_agent_harness.eval.protocols import (
    AgentResponse,
    EvalCase,
    EvalResult,
    EvalTurnResult,
)
from myrm_agent_harness.eval.significance import (
    SignificanceVerdict,
    _chi2_one_df_p_value,
    _compute_continuous_bootstrap_ci,
    _exact_binomial_two_tailed,
    calculate_paired_significance,
)


class TestSignificanceMath:
    """Tests for zero-dependency statistical math routines."""

    def test_exact_binomial_edge_cases(self) -> None:
        assert _exact_binomial_two_tailed(0, 0) == 1.0
        assert _exact_binomial_two_tailed(0, 1) == 1.0
        assert _exact_binomial_two_tailed(5, 10) == 1.0

    def test_exact_binomial_known_values(self) -> None:
        # For k=0, n=10: sum_{i=0}^0 comb(10, i) * 0.5^10 = 1 * (1/1024)
        # two-tailed p-value = 2 / 1024 = 0.001953125
        p = _exact_binomial_two_tailed(0, 10)
        assert math.isclose(p, 2.0 / 1024.0, rel_tol=1e-5)

        # For k=1, n=8: (comb(8,0) + comb(8,1)) * 0.5^8 = 9 / 256
        # two-tailed p-value = 18 / 256 = 0.0703125
        p_8 = _exact_binomial_two_tailed(1, 8)
        assert math.isclose(p_8, 18.0 / 256.0, rel_tol=1e-5)

    def test_chi2_one_df_p_value(self) -> None:
        assert _chi2_one_df_p_value(0.0) == 1.0
        assert _chi2_one_df_p_value(-2.5) == 1.0

        # Critical value for alpha = 0.05 is chi2 = 3.8414588
        p_05 = _chi2_one_df_p_value(3.8414588)
        assert math.isclose(p_05, 0.05, abs_tol=1e-3)

        # Critical value for alpha = 0.01 is chi2 = 6.6348966
        p_01 = _chi2_one_df_p_value(6.6348966)
        assert math.isclose(p_01, 0.01, abs_tol=1e-3)

    def test_continuous_bootstrap_ci(self) -> None:
        diffs = [0.1, 0.2, 0.3, 0.4, 0.5]
        mean_v, low_v, high_v = _compute_continuous_bootstrap_ci(diffs, runs=500, seed=42)
        assert math.isclose(mean_v, 0.3, rel_tol=1e-5)
        assert low_v <= mean_v <= high_v

        # All identical diffs return exact mean
        same_diffs = [0.2, 0.2, 0.2]
        s_mean, s_low, s_high = _compute_continuous_bootstrap_ci(same_diffs, runs=100)
        assert math.isclose(s_mean, 0.2, rel_tol=1e-5)
        assert math.isclose(s_low, 0.2, rel_tol=1e-5)
        assert math.isclose(s_high, 0.2, rel_tol=1e-5)


class TestPairedSignificanceAssessment:
    """Tests for calculate_paired_significance and verdict determination."""

    def test_empty_cases_boundary(self) -> None:
        res = calculate_paired_significance([], [])
        assert res.verdict == SignificanceVerdict.INSUFFICIENT_DISCORDANCE
        assert res.base_pass_rate == 0.0
        assert res.candidate_pass_rate == 0.0
        assert res.delta_pass_rate == 0.0
        assert res.mcnemar.test_type == "no_discordant_pairs"
        assert res.bootstrap_ci.crosses_zero is True
        assert res.plateau.mechanism == PlateauMechanism.HARD_SUBSET_BOTTLENECK

    def test_zero_discordant_pairs(self) -> None:
        # Both configurations have identical 80% pass outcomes
        base = [True] * 8 + [False] * 2
        cand = [True] * 8 + [False] * 2

        res = calculate_paired_significance(base, cand)
        assert res.verdict == SignificanceVerdict.INSUFFICIENT_DISCORDANCE
        assert res.mcnemar.statistic == 0.0
        assert res.mcnemar.p_value == 1.0
        assert res.mcnemar.test_type == "no_discordant_pairs"
        assert res.bootstrap_ci.crosses_zero is True
        assert res.regression_case_indices == []
        assert res.improved_case_indices == []
        assert res.plateau.mechanism == PlateauMechanism.HARD_SUBSET_BOTTLENECK

    def test_small_sample_exact_binomial_significant(self) -> None:
        # Candidate improved 10 cases, Baseline improved 0 cases out of 10 discordant
        base = [False] * 10
        cand = [True] * 10

        res = calculate_paired_significance(base, cand, alpha=0.05, bootstrap_runs=500)
        assert res.mcnemar.test_type == "exact_binomial"
        assert res.mcnemar.is_significant is True
        assert res.mcnemar.p_value < 0.01
        assert res.bootstrap_ci.crosses_zero is False
        assert res.verdict == SignificanceVerdict.SIGNIFICANT_IMPROVEMENT
        assert len(res.improved_case_indices) == 10
        assert len(res.regression_case_indices) == 0

    def test_large_sample_edwards_chi2_regression(self) -> None:
        # 30 discordant pairs: baseline passed 28, candidate passed 2 -> severe regression
        base = [True] * 28 + [False] * 2
        cand = [False] * 28 + [True] * 2

        res = calculate_paired_significance(base, cand, alpha=0.05, bootstrap_runs=500)
        assert res.mcnemar.test_type == "edwards_continuity_chi2"
        assert res.mcnemar.is_significant is True
        assert res.verdict == SignificanceVerdict.SIGNIFICANT_REGRESSION
        assert len(res.regression_case_indices) == 28
        assert len(res.improved_case_indices) == 2

    def test_efficiency_breakthrough(self) -> None:
        # Same accuracy, but candidate reduces token usage by 30%
        base_outcomes = [True] * 10
        cand_outcomes = [True] * 10
        base_tokens = [1000] * 10
        cand_tokens = [700] * 10  # -30%
        base_costs = [0.01] * 10
        cand_costs = [0.007] * 10
        base_ms = [500.0] * 10
        cand_ms = [400.0] * 10

        res = calculate_paired_significance(
            base_outcomes,
            cand_outcomes,
            base_tokens=base_tokens,
            candidate_tokens=cand_tokens,
            base_costs=base_costs,
            candidate_costs=cand_costs,
            base_ms=base_ms,
            candidate_ms=cand_ms,
            bootstrap_runs=300,
        )
        assert res.verdict == SignificanceVerdict.EFFICIENCY_BREAKTHROUGH
        assert res.continuous_delta is not None
        assert res.continuous_delta.token_diff_pct < -0.25
        assert res.continuous_delta.token_ci_95[1] < 0.0

    def test_to_dict_serialization(self) -> None:
        base = [True, False, True]
        cand = [True, True, False]
        res = calculate_paired_significance(base, cand, base_id="b1", candidate_id="c1")
        data = res.to_dict()
        assert data["base_id"] == "b1"
        assert data["candidate_id"] == "c1"
        assert "mcnemar" in data
        assert "bootstrap_ci" in data
        assert "plateau" in data
        assert "verdict" in data
        assert isinstance(data["regression_case_indices"], list)
        assert isinstance(data["improved_case_indices"], list)


class TestPlateauDiagnosisMechanisms:
    """Tests for the 4 canonical Meta-Harness plateau mechanisms."""

    def test_hard_subset_bottleneck(self) -> None:
        diag = diagnose_plateau(
            total_cases=20,
            discordant_count=0,
            base_pass_rate=0.7,
            cand_pass_rate=0.7,
            p_value=1.0,
            ci_crosses_zero=True,
            regressions_count=0,
        )
        assert diag.mechanism == PlateauMechanism.HARD_SUBSET_BOTTLENECK
        assert diag.suggested_action == "expand_tools_or_context"

    def test_capability_saturation(self) -> None:
        diag = diagnose_plateau(
            total_cases=50,
            discordant_count=3,
            base_pass_rate=0.94,
            cand_pass_rate=0.96,
            p_value=0.5,
            ci_crosses_zero=True,
            regressions_count=1,
        )
        assert diag.mechanism == PlateauMechanism.CAPABILITY_SATURATION
        assert diag.suggested_action == "introduce_hard_benchmark"

    def test_insufficient_statistical_power(self) -> None:
        diag = diagnose_plateau(
            total_cases=8,  # < 10 cases
            discordant_count=2,  # < 5 discordant
            base_pass_rate=0.5,
            cand_pass_rate=0.75,
            p_value=0.5,
            ci_crosses_zero=True,
            regressions_count=0,
        )
        assert diag.mechanism == PlateauMechanism.INSUFFICIENT_POWER
        assert diag.suggested_action == "increase_trials_or_dataset"

    def test_cross_model_divergence(self) -> None:
        diag = diagnose_plateau(
            total_cases=30,
            discordant_count=6,
            base_pass_rate=0.6,
            cand_pass_rate=0.63,
            p_value=0.68,  # Not significant (p >= 0.05)
            ci_crosses_zero=True,
            regressions_count=2,  # Regressions present
        )
        assert diag.mechanism == PlateauMechanism.CROSS_MODEL_DIVERGENCE
        assert diag.suggested_action == "reject_and_investigate_regressions"

    def test_none_valid_signal(self) -> None:
        diag = diagnose_plateau(
            total_cases=100,
            discordant_count=25,
            base_pass_rate=0.5,
            cand_pass_rate=0.75,
            p_value=0.001,
            ci_crosses_zero=False,
            regressions_count=0,
        )
        assert diag.mechanism == PlateauMechanism.NONE
        assert diag.suggested_action == "proceed_with_gate"


class TestMatrixResultSignificanceIntegration:
    """Tests for paired significance integration in MatrixResult."""

    def test_matrix_result_paired_significance_property(self) -> None:
        cases = [
            EvalCase(message="c1"),
            EvalCase(message="c2"),
            EvalCase(message="c3"),
        ]

        # Profile 1: passes c1, c2 (fails c3)
        t1 = [
            EvalTurnResult(case=cases[0], response=AgentResponse(answer="ok", cost=0.001), assertion_passed=True),
            EvalTurnResult(case=cases[1], response=AgentResponse(answer="ok", cost=0.001), assertion_passed=True),
            EvalTurnResult(case=cases[2], response=AgentResponse(answer="err", cost=0.001), assertion_passed=False),
        ]
        r1 = EvalResult(turn_results=t1, total_ms=300.0)

        # Profile 2: passes c1, c3 (fails c2)
        t2 = [
            EvalTurnResult(case=cases[0], response=AgentResponse(answer="ok", cost=0.001), assertion_passed=True),
            EvalTurnResult(case=cases[1], response=AgentResponse(answer="err", cost=0.001), assertion_passed=False),
            EvalTurnResult(case=cases[2], response=AgentResponse(answer="ok", cost=0.001), assertion_passed=True),
        ]
        r2 = EvalResult(turn_results=t2, total_ms=350.0)

        matrix_res = MatrixResult(
            profile_ids=["p1", "p2"],
            cases=cases,
            per_profile_results={"p1": r1, "p2": r2},
            total_ms=650.0,
        )

        sig_map = matrix_res.paired_significance
        assert "p1:p2" in sig_map
        p1_p2 = sig_map["p1:p2"]
        assert p1_p2["base_id"] == "p1"
        assert p1_p2["candidate_id"] == "p2"
        assert "mcnemar" in p1_p2
        assert "bootstrap_ci" in p1_p2
        assert "plateau" in p1_p2

        # Verify to_dict serialization
        exported = matrix_res.to_dict()
        assert "paired_significance" in exported
        sig_data = exported["paired_significance"]
        assert isinstance(sig_data, dict)
        assert "p1:p2" in sig_data
