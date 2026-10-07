"""Three-stage lifecycle governor for procedural judgment rules.

[INPUT]
- toolkits.memory.crystallization.types::CrystallizedRuleMetrics, ImportanceScoreResult, RuleLifecycleState
  (POS: Typed data contracts for the crystallization subsystem.)

[OUTPUT]
- ProceduralCrystallizationGovernor: Three-stage lifecycle governor for procedural judgment rules.

[POS]
Three-stage lifecycle governor for procedural judgment rules.
"""

from collections import defaultdict

from .types import (
    CrystallizedRuleMetrics,
    ImportanceScoreResult,
    RuleLifecycleState,
)


class ProceduralCrystallizationGovernor:
    """Three-stage lifecycle governor for procedural judgment rules."""

    def __init__(
        self,
        importance_threshold: float = 0.70,
        min_trials_for_transition: int = 3,
        degrade_threshold: float = 0.40,
        retire_threshold: float = 0.20,
        recover_threshold: float = 0.60,
    ) -> None:
        self._importance_threshold = importance_threshold
        self._min_trials = min_trials_for_transition
        self._degrade_threshold = degrade_threshold
        self._retire_threshold = retire_threshold
        self._recover_threshold = recover_threshold

        self._rules: dict[str, CrystallizedRuleMetrics] = {}
        self._session_invocations: dict[str, set[str]] = defaultdict(set)

    def evaluate_formation_gate(
        self,
        confidence: float,
        severity: float,
        content: str = "",
    ) -> ImportanceScoreResult:
        """Evaluate two-factor importance gate (confidence x severity) to eliminate trivial noise."""
        conf = max(0.0, min(1.0, confidence))
        sev = max(0.0, min(1.0, severity))
        importance = round(conf * sev, 4)
        passed = importance >= self._importance_threshold

        if passed:
            reason = (
                f"Importance score {importance:.4f} >= {self._importance_threshold:.2f} threshold. "
                "High-signal procedural rule approved for crystallization."
            )
        else:
            reason = (
                f"Importance score {importance:.4f} < {self._importance_threshold:.2f} threshold. "
                "Filtered out as low-signal ephemeral noise or trivial dialogue."
            )

        return ImportanceScoreResult(
            confidence=conf,
            severity=sev,
            importance=importance,
            passed_gate=passed,
            gate_reason=reason,
        )

    def filter_by_facets(
        self,
        rules: list[CrystallizedRuleMetrics],
        active_facets: list[str],
    ) -> list[CrystallizedRuleMetrics]:
        """Filter and rank active rules scoped to current agent operational facets."""
        # Retired rules are categorically excluded from context injection
        non_retired = [r for r in rules if r.state != RuleLifecycleState.RETIRED]

        if not active_facets or "global" in active_facets:
            # Global scope allows global rules and all non-retired rules
            matching = non_retired
        else:
            target_facets = set(active_facets)
            matching = [
                r for r in non_retired
                if "global" in r.facets or bool(set(r.facets) & target_facets)
            ]

        # Prioritize higher-weight active rules first
        return sorted(matching, key=lambda x: x.weight, reverse=True)

    def record_execution_feedback(
        self,
        rule_id: str,
        session_id: str,
        is_success: bool,
        secondary_error_occurred: bool = False,
        description: str = "",
        facets: list[str] | None = None,
    ) -> CrystallizedRuleMetrics:
        """Process execution outcome, apply same-session repeat error penalty, and evolve lifecycle state."""
        metrics = self._get_or_create_rule(rule_id, description=description, facets=facets)

        # Detect secondary repetition in same session
        already_invoked = rule_id in self._session_invocations[session_id]
        is_repeat_failure = bool(
            not is_success and (secondary_error_occurred or already_invoked)
        )
        self._session_invocations[session_id].add(rule_id)

        failure_penalty = 0.35 if is_repeat_failure else 0.0

        if is_success:
            metrics.success_count += 1
        else:
            # Secondary error in same session increments penalty count harder
            metrics.fail_count += 2 if is_repeat_failure else 1

        total_trials = metrics.success_count + metrics.fail_count
        metrics.win_rate = (
            round(metrics.success_count / total_trials, 4) if total_trials > 0 else 1.0
        )

        # Transition state machine based on empirical win-rate thresholds
        if total_trials >= self._min_trials:
            if metrics.win_rate < self._retire_threshold:
                metrics.state = RuleLifecycleState.RETIRED
            elif metrics.win_rate < self._degrade_threshold:
                metrics.state = RuleLifecycleState.DEGRADED
            elif metrics.win_rate >= self._recover_threshold:
                metrics.state = RuleLifecycleState.ACTIVE

        # Calculate scheduling weight
        if metrics.state == RuleLifecycleState.RETIRED:
            metrics.weight = 0.0
        elif metrics.state == RuleLifecycleState.DEGRADED:
            degraded_base = metrics.win_rate * 0.5
            metrics.weight = round(max(0.05, degraded_base - failure_penalty), 4)
        else:
            metrics.weight = round(max(0.1, min(1.0, metrics.win_rate - failure_penalty)), 4)

        return metrics

    def get_metrics(self, rule_id: str) -> CrystallizedRuleMetrics | None:
        """Fetch current telemetry and lifecycle status for a crystallized rule."""
        return self._rules.get(rule_id)

    def register_rule(
        self,
        rule_id: str,
        facets: list[str] | None = None,
        description: str = "",
        initial_state: RuleLifecycleState = RuleLifecycleState.ACTIVE,
    ) -> CrystallizedRuleMetrics:
        """Explicitly register a new rule in the governor."""
        rule_facets = facets if facets is not None else ["global"]
        metrics = CrystallizedRuleMetrics(
            rule_id=rule_id,
            facets=rule_facets,
            success_count=0,
            fail_count=0,
            win_rate=1.0,
            state=initial_state,
            weight=1.0 if initial_state == RuleLifecycleState.ACTIVE else 0.5,
            description=description,
        )
        self._rules[rule_id] = metrics
        return metrics

    def _get_or_create_rule(
        self,
        rule_id: str,
        description: str = "",
        facets: list[str] | None = None,
    ) -> CrystallizedRuleMetrics:
        """Retrieve existing rule metrics or initialize new active record."""
        if rule_id not in self._rules:
            self._rules[rule_id] = self.register_rule(
                rule_id=rule_id,
                facets=facets,
                description=description,
            )
        return self._rules[rule_id]
