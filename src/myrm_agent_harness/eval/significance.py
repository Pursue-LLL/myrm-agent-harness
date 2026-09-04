"""Statistical significance testing and plateau diagnosis for paired agent evaluations.

[INPUT]
- math, random, dataclasses, enum (POS: standard library)
- .plateau::PlateauMechanism (POS: plateau mechanisms enum)
- .plateau::PlateauDiagnosis (POS: structured honest plateau diagnosis)
- .plateau::diagnose_plateau (POS: deterministic plateau diagnosis function)

[OUTPUT]
- SignificanceVerdict: enum of significance classification
- McNemarResult: outcome of McNemar paired test
- BootstrapCIResult: outcome of paired Bootstrap confidence interval
- ContinuousMetricsDelta: continuous delta and 95% bootstrap CI
- PairedSignificanceAssessment: consolidated paired significance evaluation
- calculate_paired_significance(): main entry point for paired evaluation

[POS]
Provides zero-LLM-cost, zero-external-dependency paired statistical hypothesis
testing (McNemar + Paired Bootstrap) and Plateau Mechanism diagnostics for
rigorous Agent evaluation without sampling noise false positives.
"""

from __future__ import annotations

import enum
import math
import random
from dataclasses import dataclass, field

from .plateau import (
    PlateauDiagnosis,
    PlateauMechanism,
    diagnose_plateau,
)

# Retain backward-compatible private alias
_diagnose_plateau = diagnose_plateau


class SignificanceVerdict(enum.StrEnum):
    """Statistical significance verdict for paired profile evaluation."""

    SIGNIFICANT_IMPROVEMENT = "significant_improvement"
    SIGNIFICANT_REGRESSION = "significant_regression"
    EFFICIENCY_BREAKTHROUGH = "efficiency_breakthrough"
    NO_SIGNIFICANT_DIFFERENCE = "no_significant_difference"
    INSUFFICIENT_DISCORDANCE = "insufficient_discordance"


@dataclass(frozen=True, slots=True)
class McNemarResult:
    """Outcome of McNemar paired test."""

    statistic: float
    p_value: float
    is_significant: bool  # p_value < alpha
    contingency_table: dict[str, int]  # {"both_pass": a, "base_only": b, "cand_only": c, "both_fail": d}
    test_type: str  # "exact_binomial" | "edwards_continuity_chi2" | "no_discordant_pairs"

    def to_dict(self) -> dict[str, object]:
        return {
            "statistic": round(self.statistic, 4),
            "p_value": round(self.p_value, 4),
            "is_significant": self.is_significant,
            "contingency_table": self.contingency_table,
            "test_type": self.test_type,
        }


@dataclass(frozen=True, slots=True)
class BootstrapCIResult:
    """Outcome of paired Bootstrap confidence interval."""

    ci_lower: float
    ci_upper: float
    delta_mean: float
    confidence_level: float = 0.95
    sample_runs: int = 1000
    crosses_zero: bool = True

    def to_dict(self) -> dict[str, object]:
        return {
            "ci_lower": round(self.ci_lower, 4),
            "ci_upper": round(self.ci_upper, 4),
            "delta_mean": round(self.delta_mean, 4),
            "confidence_level": self.confidence_level,
            "sample_runs": self.sample_runs,
            "crosses_zero": self.crosses_zero,
        }


@dataclass(frozen=True, slots=True)
class ContinuousMetricsDelta:
    """Paired continuous resource & latency deltas with 95% bootstrap confidence intervals."""

    token_diff_pct: float = 0.0
    token_ci_95: tuple[float, float] = (0.0, 0.0)
    cost_diff_pct: float = 0.0
    cost_ci_95: tuple[float, float] = (0.0, 0.0)
    latency_diff_pct: float = 0.0
    latency_ci_95: tuple[float, float] = (0.0, 0.0)

    def to_dict(self) -> dict[str, object]:
        return {
            "token_diff_pct": round(self.token_diff_pct, 4),
            "token_ci_95": [round(x, 4) for x in self.token_ci_95],
            "cost_diff_pct": round(self.cost_diff_pct, 4),
            "cost_ci_95": [round(x, 4) for x in self.cost_ci_95],
            "latency_diff_pct": round(self.latency_diff_pct, 4),
            "latency_ci_95": [round(x, 4) for x in self.latency_ci_95],
        }


@dataclass(frozen=True, slots=True)
class PairedSignificanceAssessment:
    """Consolidated paired significance evaluation for two agent configurations."""

    base_id: str
    candidate_id: str
    base_pass_rate: float
    candidate_pass_rate: float
    delta_pass_rate: float
    mcnemar: McNemarResult
    bootstrap_ci: BootstrapCIResult
    plateau: PlateauDiagnosis
    verdict: SignificanceVerdict = SignificanceVerdict.NO_SIGNIFICANT_DIFFERENCE
    regression_case_indices: list[int] = field(default_factory=list)
    improved_case_indices: list[int] = field(default_factory=list)
    continuous_delta: ContinuousMetricsDelta | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "base_id": self.base_id,
            "candidate_id": self.candidate_id,
            "base_pass_rate": round(self.base_pass_rate, 4),
            "candidate_pass_rate": round(self.candidate_pass_rate, 4),
            "delta_pass_rate": round(self.delta_pass_rate, 4),
            "mcnemar": self.mcnemar.to_dict(),
            "bootstrap_ci": self.bootstrap_ci.to_dict(),
            "plateau": self.plateau.to_dict(),
            "verdict": self.verdict.value,
            "regression_case_indices": self.regression_case_indices,
            "improved_case_indices": self.improved_case_indices,
            "continuous_delta": (
                self.continuous_delta.to_dict() if self.continuous_delta else None
            ),
        }


def _exact_binomial_two_tailed(k: int, n: int) -> float:
    """Exact two-tailed p-value for binomial test with p=0.5.

    Uses math.comb to compute the cumulative sum for i <= k.
    """
    if n == 0:
        return 1.0
    cum_prob = 0.0
    for i in range(k + 1):
        cum_prob += math.comb(n, i)
    cum_prob *= 0.5**n
    return min(1.0, 2.0 * cum_prob)


def _chi2_one_df_p_value(chi2: float) -> float:
    """Survival function (p-value) for Chi-Square distribution with df=1.

    Since for X ~ N(0, 1), X^2 ~ Chi2(1), P(Chi2 >= c) = erfc(sqrt(c / 2)).
    """
    if chi2 <= 0.0:
        return 1.0
    return math.erfc(math.sqrt(chi2 / 2.0))


def _compute_continuous_bootstrap_ci(
    diffs: list[float],
    *,
    runs: int = 1000,
    seed: int = 42,
) -> tuple[float, float, float]:
    """Helper to compute deterministic bootstrap CI for continuous deltas."""
    if not diffs:
        return 0.0, 0.0, 0.0
    n = len(diffs)
    mean_val = sum(diffs) / n
    if all(d == diffs[0] for d in diffs):
        return mean_val, mean_val, mean_val

    rng = random.Random(seed)
    boot_means: list[float] = []
    for _ in range(runs):
        sample = rng.choices(diffs, k=n)
        boot_means.append(sum(sample) / n)

    boot_means.sort()
    low_idx = max(0, min(int(0.025 * runs), runs - 1))
    high_idx = max(0, min(int(0.975 * runs), runs - 1))
    return mean_val, boot_means[low_idx], boot_means[high_idx]


def calculate_paired_significance(
    base_outcomes: list[bool],
    candidate_outcomes: list[bool],
    *,
    base_id: str = "baseline",
    candidate_id: str = "candidate",
    alpha: float = 0.05,
    bootstrap_runs: int = 1000,
    seed: int = 42,
    base_tokens: list[int] | None = None,
    candidate_tokens: list[int] | None = None,
    base_costs: list[float] | None = None,
    candidate_costs: list[float] | None = None,
    base_ms: list[float] | None = None,
    candidate_ms: list[float] | None = None,
) -> PairedSignificanceAssessment:
    """Calculate McNemar test, Bootstrap 95% CI, and Plateau Diagnosis for paired results."""
    n = min(len(base_outcomes), len(candidate_outcomes))
    if n == 0:
        empty_mcnemar = McNemarResult(
            statistic=0.0,
            p_value=1.0,
            is_significant=False,
            contingency_table={"both_pass": 0, "base_only": 0, "cand_only": 0, "both_fail": 0},
            test_type="no_discordant_pairs",
        )
        empty_ci = BootstrapCIResult(ci_lower=0.0, ci_upper=0.0, delta_mean=0.0, sample_runs=0, crosses_zero=True)
        empty_plateau = PlateauDiagnosis(
            mechanism=PlateauMechanism.HARD_SUBSET_BOTTLENECK,
            title="Empty Set",
            explanation="No cases provided for paired evaluation.",
            recommendation="Provide valid eval cases.",
            suggested_action="none",
        )
        return PairedSignificanceAssessment(
            base_id=base_id,
            candidate_id=candidate_id,
            base_pass_rate=0.0,
            candidate_pass_rate=0.0,
            delta_pass_rate=0.0,
            mcnemar=empty_mcnemar,
            bootstrap_ci=empty_ci,
            plateau=empty_plateau,
            verdict=SignificanceVerdict.INSUFFICIENT_DISCORDANCE,
        )

    a, b, c, d = 0, 0, 0, 0
    regression_indices: list[int] = []
    improved_indices: list[int] = []
    diffs: list[float] = []

    for idx in range(n):
        b_pass = bool(base_outcomes[idx])
        c_pass = bool(candidate_outcomes[idx])
        diffs.append(1.0 if c_pass else 0.0)
        # compute pair
        if b_pass and c_pass:
            a += 1
        elif b_pass and not c_pass:
            b += 1
            regression_indices.append(idx)
        elif not b_pass and c_pass:
            c += 1
            improved_indices.append(idx)
        else:
            d += 1

    base_rate = round((a + b) / n, 4)
    cand_rate = round((a + c) / n, 4)
    delta_rate = round(cand_rate - base_rate, 4)

    table = {"both_pass": a, "base_only": b, "cand_only": c, "both_fail": d}
    discordant = b + c

    if discordant == 0:
        mcnemar = McNemarResult(
            statistic=0.0,
            p_value=1.0,
            is_significant=False,
            contingency_table=table,
            test_type="no_discordant_pairs",
        )
    elif discordant < 25:
        k = min(b, c)
        p_val = _exact_binomial_two_tailed(k, discordant)
        mcnemar = McNemarResult(
            statistic=float(k),
            p_value=p_val,
            is_significant=(p_val < alpha),
            contingency_table=table,
            test_type="exact_binomial",
        )
    else:
        # Edwards continuity-corrected McNemar Chi-Square
        chi2 = ((abs(b - c) - 1.0) ** 2) / float(discordant)
        p_val = _chi2_one_df_p_value(chi2)
        mcnemar = McNemarResult(
            statistic=chi2,
            p_value=p_val,
            is_significant=(p_val < alpha),
            contingency_table=table,
            test_type="edwards_continuity_chi2",
        )

    # Paired Bootstrap CI on delta pass rate
    paired_deltas = [(1.0 if candidate_outcomes[i] else 0.0) - (1.0 if base_outcomes[i] else 0.0) for i in range(n)]

    if discordant == 0:
        bootstrap_ci = BootstrapCIResult(
            ci_lower=0.0,
            ci_upper=0.0,
            delta_mean=0.0,
            confidence_level=0.95,
            sample_runs=bootstrap_runs,
            crosses_zero=True,
        )
    else:
        rng = random.Random(seed)
        sampled_deltas: list[float] = []
        for _ in range(bootstrap_runs):
            sample = rng.choices(paired_deltas, k=n)
            sampled_deltas.append(sum(sample) / n)

        sampled_deltas.sort()
        # 95% CI: 2.5% and 97.5% quantiles
        lower_idx = int(bootstrap_runs * 0.025)
        upper_idx = min(int(bootstrap_runs * 0.975), bootstrap_runs - 1)
        ci_lower = max(-1.0, min(1.0, sampled_deltas[lower_idx]))
        ci_upper = max(-1.0, min(1.0, sampled_deltas[upper_idx]))
        crosses_zero = (ci_lower <= 0.0 <= ci_upper)

        bootstrap_ci = BootstrapCIResult(
            ci_lower=ci_lower,
            ci_upper=ci_upper,
            delta_mean=delta_rate,
            confidence_level=0.95,
            sample_runs=bootstrap_runs,
            crosses_zero=crosses_zero,
        )

    plateau = _diagnose_plateau(
        total_cases=n,
        discordant_count=discordant,
        base_pass_rate=base_rate,
        cand_pass_rate=cand_rate,
        p_value=mcnemar.p_value,
        ci_crosses_zero=bootstrap_ci.crosses_zero,
        regressions_count=len(regression_indices),
    )

    continuous_delta: ContinuousMetricsDelta | None = None
    if base_tokens and candidate_tokens and len(base_tokens) == n and len(candidate_tokens) == n:
        tok_diffs = [
            max(-10.0, min(10.0, (candidate_tokens[i] - base_tokens[i]) / max(1, base_tokens[i])))
            for i in range(n)
        ]
        t_mean, t_low, t_high = _compute_continuous_bootstrap_ci(tok_diffs, runs=bootstrap_runs, seed=seed)

        def _calc_cost_diff(b_val: float, c_val: float) -> float:
            if abs(b_val) < 1e-6 and abs(c_val) < 1e-6:
                return 0.0
            denom = max(1e-4, b_val)
            return max(-10.0, min(10.0, (c_val - b_val) / denom))

        c_diffs = (
            [_calc_cost_diff(base_costs[i], candidate_costs[i]) for i in range(n)]
            if base_costs and candidate_costs and len(base_costs) == n and len(candidate_costs) == n
            else [0.0] * n
        )
        c_mean, c_low, c_high = _compute_continuous_bootstrap_ci(c_diffs, runs=bootstrap_runs, seed=seed)

        m_diffs = (
            [
                max(-10.0, min(10.0, (candidate_ms[i] - base_ms[i]) / max(1.0, base_ms[i])))
                for i in range(n)
            ]
            if base_ms and candidate_ms and len(base_ms) == n and len(candidate_ms) == n
            else [0.0] * n
        )
        m_mean, m_low, m_high = _compute_continuous_bootstrap_ci(m_diffs, runs=bootstrap_runs, seed=seed)

        continuous_delta = ContinuousMetricsDelta(
            token_diff_pct=t_mean,
            token_ci_95=(t_low, t_high),
            cost_diff_pct=c_mean,
            cost_ci_95=(c_low, c_high),
            latency_diff_pct=m_mean,
            latency_ci_95=(m_low, m_high),
        )

    # Assign verdict
    if (
        continuous_delta
        and continuous_delta.token_diff_pct < -0.15
        and continuous_delta.token_ci_95[1] < 0
        and len(regression_indices) <= len(improved_indices)
    ):
        verdict = SignificanceVerdict.EFFICIENCY_BREAKTHROUGH
    elif discordant == 0:
        verdict = SignificanceVerdict.INSUFFICIENT_DISCORDANCE
    elif mcnemar.is_significant and delta_rate > 0 and not bootstrap_ci.crosses_zero:
        verdict = SignificanceVerdict.SIGNIFICANT_IMPROVEMENT
    elif mcnemar.is_significant and delta_rate < 0 and not bootstrap_ci.crosses_zero:
        verdict = SignificanceVerdict.SIGNIFICANT_REGRESSION
    else:
        verdict = SignificanceVerdict.NO_SIGNIFICANT_DIFFERENCE

    return PairedSignificanceAssessment(
        base_id=base_id,
        candidate_id=candidate_id,
        base_pass_rate=base_rate,
        candidate_pass_rate=cand_rate,
        delta_pass_rate=delta_rate,
        mcnemar=mcnemar,
        bootstrap_ci=bootstrap_ci,
        plateau=plateau,
        verdict=verdict,
        regression_case_indices=regression_indices,
        improved_case_indices=improved_indices,
        continuous_delta=continuous_delta,
    )
