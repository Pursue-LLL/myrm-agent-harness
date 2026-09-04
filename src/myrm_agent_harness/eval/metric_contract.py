"""Metric Contract SSOT & Proxy Alignment Guard.

[INPUT]
- dataclasses, enum, typing (POS: Python standard library)

[OUTPUT]
- ProxyAlignmentVerdict: Lifecycle alignment status (ALIGNED, ACCEPTED_TRADEOFF, GOODHART_DRIFT, UNCONVERGED)
- MetricIntentSpec: Specification for primary core intent metrics
- MetricProxySpec: Specification for proxy cost/efficiency metrics
- MetricContract: SSOT data contract binding primary intents with proxy metrics
- MetricDriftAnalysis: Quantitative drift analysis report
- evaluate_metric_proxy_alignment(): Zero-LLM deterministic proxy drift detection

[POS]
Harness framework layer evaluation component implementing Continual Harness Metric Shaping
protection. Detects Goodhart's Law metric drift where candidate variants cut corners on
core fidelity to maximize superficial efficiency gains (steps/tokens/tool_calls).
"""

from __future__ import annotations

from dataclasses import dataclass, field
import enum


class ProxyAlignmentVerdict(enum.StrEnum):
    """Verdict on alignment between primary user intent and proxy metrics."""

    ALIGNED = "aligned"  # Core intent improved or maintained while proxies optimized
    ACCEPTED_TRADEOFF = "accepted_tradeoff"  # Minor core fluctuation within tolerance for massive proxy gain
    GOODHART_DRIFT = "goodhart_drift"  # Goodhart's law violation: proxies surged while core intent regressed
    UNCONVERGED = "unconverged"  # Insufficient sample size or missing core metrics to establish confidence


@dataclass(frozen=True, slots=True)
class MetricIntentSpec:
    """Specification of a primary core intent metric (e.g. pass_rate, fact_accuracy)."""

    name: str
    higher_is_better: bool = True
    weight: float = 1.0
    tolerance: float = 0.05  # Permissible negative delta before triggering regression alert


@dataclass(frozen=True, slots=True)
class MetricProxySpec:
    """Specification of a proxy efficiency/cost metric (e.g. tokens, steps, latency)."""

    name: str
    higher_is_better: bool = False  # By default, lower cost/latency/steps is better
    is_forbidden_as_sole_criterion: bool = True  # Disallow adopting based solely on this proxy optimizing


@dataclass(frozen=True, slots=True)
class MetricContract:
    """SSOT contract constraining allowed trade-offs between core intent and proxy metrics."""

    contract_id: str
    description: str = ""
    primary_intents: tuple[MetricIntentSpec, ...] = field(
        default_factory=lambda: (
            MetricIntentSpec(name="pass_rate", higher_is_better=True, weight=1.0, tolerance=0.03),
            MetricIntentSpec(name="success_rate", higher_is_better=True, weight=1.0, tolerance=0.03),
        )
    )
    proxies: tuple[MetricProxySpec, ...] = field(
        default_factory=lambda: (
            MetricProxySpec(name="tokens", higher_is_better=False, is_forbidden_as_sole_criterion=True),
            MetricProxySpec(name="duration_ms", higher_is_better=False, is_forbidden_as_sole_criterion=True),
            MetricProxySpec(name="tool_calls", higher_is_better=False, is_forbidden_as_sole_criterion=True),
        )
    )
    min_sample_size: int = 5  # Confidence threshold to suppress noise false positives

    def to_dict(self) -> dict[str, object]:
        """Serialize contract to dictionary."""
        return {
            "contract_id": self.contract_id,
            "description": self.description,
            "min_sample_size": self.min_sample_size,
            "primary_intents": [
                {
                    "name": spec.name,
                    "higher_is_better": spec.higher_is_better,
                    "weight": spec.weight,
                    "tolerance": spec.tolerance,
                }
                for spec in self.primary_intents
            ],
            "proxies": [
                {
                    "name": spec.name,
                    "higher_is_better": spec.higher_is_better,
                    "is_forbidden_as_sole_criterion": spec.is_forbidden_as_sole_criterion,
                }
                for spec in self.proxies
            ],
        }


@dataclass(frozen=True, slots=True)
class MetricDriftAnalysis:
    """Analytical evaluation report for metric proxy alignment."""

    contract_id: str
    verdict: ProxyAlignmentVerdict
    sample_size: int
    intent_delta: float  # Weighted delta of core intent (-1.0 to 1.0)
    proxy_improvement: float  # Weighted relative improvement of proxy metrics (0.0 to 1.0+)
    flagged_proxies: tuple[str, ...] = field(default_factory=tuple)
    warning_message: str = ""

    def to_dict(self) -> dict[str, object]:
        """Serialize analysis result to dictionary."""
        return {
            "contract_id": self.contract_id,
            "verdict": self.verdict.value,
            "sample_size": self.sample_size,
            "intent_delta": round(self.intent_delta, 4),
            "proxy_improvement": round(self.proxy_improvement, 4),
            "flagged_proxies": list(self.flagged_proxies),
            "warning_message": self.warning_message,
        }


def _calculate_relative_improvement(
    baseline: float, candidate: float, higher_is_better: bool
) -> float:
    """Calculate normalized relative improvement. Positive means better."""
    if higher_is_better:
        if baseline == 0.0:
            return 1.0 if candidate > 0.0 else 0.0
        return (candidate - baseline) / abs(baseline)
    # Lower is better (e.g. latency, tokens)
    if baseline == 0.0:
        return -1.0 if candidate > 0.0 else 0.0
    return (baseline - candidate) / abs(baseline)


def evaluate_metric_proxy_alignment(
    baseline_metrics: dict[str, float],
    candidate_metrics: dict[str, float],
    contract: MetricContract | None = None,
    *,
    sample_size: int = 10,
) -> MetricDriftAnalysis:
    """Evaluate whether candidate metrics represent true intent alignment or Goodhart's Law drift.

    Deterministic zero-LLM evaluator enforcing the Metric Shaping Protection protocol.
    """
    effective_contract = contract or MetricContract(contract_id="default_alignment_contract")

    # 1. Sample size confidence check
    if sample_size < effective_contract.min_sample_size:
        return MetricDriftAnalysis(
            contract_id=effective_contract.contract_id,
            verdict=ProxyAlignmentVerdict.UNCONVERGED,
            sample_size=sample_size,
            intent_delta=0.0,
            proxy_improvement=0.0,
            warning_message=(
                f"Sample size ({sample_size}) is below confidence threshold "
                f"({effective_contract.min_sample_size}). Alignment inconclusive."
            ),
        )

    # 2. Evaluate Primary Intents
    total_intent_weight = 0.0
    weighted_intent_delta = 0.0
    matched_intents = 0
    max_tolerance = 0.03

    for spec in effective_contract.primary_intents:
        if spec.name in baseline_metrics and spec.name in candidate_metrics:
            b_val = float(baseline_metrics[spec.name])
            c_val = float(candidate_metrics[spec.name])
            delta = _calculate_relative_improvement(b_val, c_val, spec.higher_is_better)
            weighted_intent_delta += delta * spec.weight
            total_intent_weight += spec.weight
            max_tolerance = max(max_tolerance, spec.tolerance)
            matched_intents += 1

    if matched_intents == 0 or total_intent_weight == 0.0:
        # No primary intent metrics matched
        return MetricDriftAnalysis(
            contract_id=effective_contract.contract_id,
            verdict=ProxyAlignmentVerdict.UNCONVERGED,
            sample_size=sample_size,
            intent_delta=0.0,
            proxy_improvement=0.0,
            warning_message="No matching primary intent metrics found in evaluation payloads.",
        )

    normalized_intent_delta = weighted_intent_delta / total_intent_weight

    # 3. Evaluate Proxy Metrics
    total_proxy_count = 0
    total_proxy_improvement = 0.0
    flagged: list[str] = []

    for p_spec in effective_contract.proxies:
        if p_spec.name in baseline_metrics and p_spec.name in candidate_metrics:
            pb_val = float(baseline_metrics[p_spec.name])
            pc_val = float(candidate_metrics[p_spec.name])
            p_imp = _calculate_relative_improvement(pb_val, pc_val, p_spec.higher_is_better)
            total_proxy_improvement += p_imp
            total_proxy_count += 1

            # Check if a forbidden sole proxy surged suspiciously while intent dropped
            if p_spec.is_forbidden_as_sole_criterion and p_imp > 0.25 and normalized_intent_delta < 0:
                flagged.append(p_spec.name)

    avg_proxy_improvement = (
        (total_proxy_improvement / total_proxy_count) if total_proxy_count > 0 else 0.0
    )

    # 4. Formulate Verdict
    # Goodhart's Law: Proxies improved significantly (>10%), but core intent suffered noticeable drop (> tolerance)
    if avg_proxy_improvement > 0.10 and normalized_intent_delta < -max_tolerance:
        flagged_str = ", ".join(flagged) if flagged else "proxy efficiency metrics"
        msg = (
            f"Goodhart's Law Drift detected: {flagged_str} improved by {avg_proxy_improvement * 100:.1f}%, "
            f"but primary intent regressed by {abs(normalized_intent_delta) * 100:.1f}%."
        )
        return MetricDriftAnalysis(
            contract_id=effective_contract.contract_id,
            verdict=ProxyAlignmentVerdict.GOODHART_DRIFT,
            sample_size=sample_size,
            intent_delta=normalized_intent_delta,
            proxy_improvement=avg_proxy_improvement,
            flagged_proxies=tuple(flagged),
            warning_message=msg,
        )

    # Accepted Trade-off: Core intent dipped slightly within tolerance, but proxies gained massively (>30%)
    if -max_tolerance <= normalized_intent_delta < 0.0 and avg_proxy_improvement >= 0.30:
        msg = (
            f"Accepted Trade-off: Core intent slight fluctuation ({normalized_intent_delta * 100:.1f}%) "
            f"is offset by massive proxy optimization (+{avg_proxy_improvement * 100:.1f}%)."
        )
        return MetricDriftAnalysis(
            contract_id=effective_contract.contract_id,
            verdict=ProxyAlignmentVerdict.ACCEPTED_TRADEOFF,
            sample_size=sample_size,
            intent_delta=normalized_intent_delta,
            proxy_improvement=avg_proxy_improvement,
            flagged_proxies=tuple(flagged),
            warning_message=msg,
        )

    # Core intent was maintained or improved
    verdict = (
        ProxyAlignmentVerdict.ALIGNED
        if normalized_intent_delta >= -max_tolerance
        else ProxyAlignmentVerdict.GOODHART_DRIFT
    )
    msg = (
        "Core intent and proxy metrics are well-aligned."
        if verdict == ProxyAlignmentVerdict.ALIGNED
        else "Core intent regressed without acceptable proxy justification."
    )

    return MetricDriftAnalysis(
        contract_id=effective_contract.contract_id,
        verdict=verdict,
        sample_size=sample_size,
        intent_delta=normalized_intent_delta,
        proxy_improvement=avg_proxy_improvement,
        flagged_proxies=tuple(flagged),
        warning_message=msg,
    )
