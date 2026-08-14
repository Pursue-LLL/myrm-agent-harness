"""Ref-not-found statistics and diagnosis behaviors.

[INPUT]
- snapshot::RefInfo (POS: element ref metadata)

[OUTPUT]
- RefNotFoundMetrics: ref failure statistics (global + sliding window failure rate, top refs/actions with cache optimization)
- RefDiagnosticsMixin: context-ref sampling and periodic failure-rate logging for the Interactor

[POS]
Ref-failure observability for the Interactor. RefNotFoundMetrics is a pure data
model with no browser dependencies, so it can be imported standalone by
benchmarks and monitoring. RefDiagnosticsMixin supplies the diagnosis behaviors
that read it: diverse context-ref sampling on failure and periodic failure-rate
logging. The host class (Interactor) owns the `_refs`/`_metrics` attributes the
mixin reads.
"""

from __future__ import annotations

import logging
from collections import defaultdict, deque
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class RefNotFoundMetrics:
    """Ref-not-found statistics data.

    Provides both global and sliding-window (last 100) failure-rate views,
    with cached top refs/actions queries.

    Attributes:
        total_failures: Total failure count.
        total_interactions: Total interaction count.
        failure_refs: Failure count per ref (ref_id -> count).
        failure_by_action: Failure count per action type.
    """

    total_failures: int = 0
    total_interactions: int = 0
    failure_refs: dict[str, int] = field(default_factory=dict)
    failure_by_action: dict[str, int] = field(default_factory=dict)

    _recent_failures: deque[bool] = field(default_factory=lambda: deque(maxlen=100), init=False, repr=False)
    _cached_top_refs: list[tuple[str, int]] | None = field(default=None, init=False, repr=False)
    _cached_top_actions: list[tuple[str, int]] | None = field(default=None, init=False, repr=False)

    def record_interaction(self, failed: bool, ref: str | None = None, action: str | None = None) -> None:
        """Record a single interaction result.

        Args:
            failed: Whether the ref lookup failed.
            ref: The failed ref ID (only required on failure).
            action: The failed action (only required on failure).
        """
        self.total_interactions += 1
        self._recent_failures.append(failed)

        if failed:
            self.total_failures += 1
            if ref:
                self.failure_refs[ref] = self.failure_refs.get(ref, 0) + 1
            if action:
                self.failure_by_action[action] = self.failure_by_action.get(action, 0) + 1
            self._invalidate_cache()

    def _invalidate_cache(self) -> None:
        """Invalidate the sorted-result cache."""
        self._cached_top_refs = None
        self._cached_top_actions = None

    @property
    def failure_rate(self) -> float:
        """Global failure rate (0.0-1.0)."""
        if self.total_interactions == 0:
            return 0.0
        return self.total_failures / self.total_interactions

    @property
    def recent_failure_rate(self) -> float:
        """Recent failure rate over the last 100 interactions (0.0-1.0)."""
        if not self._recent_failures:
            return 0.0
        return sum(self._recent_failures) / len(self._recent_failures)

    @property
    def top_failed_refs(self) -> list[tuple[str, int]]:
        """Top failed refs sorted by count descending (max 10, cached)."""
        if self._cached_top_refs is None:
            self._cached_top_refs = sorted(self.failure_refs.items(), key=lambda x: x[1], reverse=True)[:10]
        return self._cached_top_refs

    @property
    def top_failed_actions(self) -> list[tuple[str, int]]:
        """Top failed actions sorted by count descending (cached)."""
        if self._cached_top_actions is None:
            self._cached_top_actions = sorted(self.failure_by_action.items(), key=lambda x: x[1], reverse=True)
        return self._cached_top_actions

    def to_dict(self) -> dict[str, object]:
        """Export metrics as a dict for logging and monitoring.

        Returns:
            Dict containing all metrics and computed properties.
        """
        return {
            "total_failures": self.total_failures,
            "total_interactions": self.total_interactions,
            "failure_rate": self.failure_rate,
            "recent_failure_rate": self.recent_failure_rate,
            "top_failed_refs": self.top_failed_refs,
            "top_failed_actions": self.top_failed_actions,
        }


class RefDiagnosticsMixin:
    """Ref-failure diagnosis behaviors for the Interactor.

    Provides diverse context-ref sampling (used when composing a
    RefNotFoundError) and periodic failure-rate logging. Reads `_refs`
    (ref_id -> RefInfo) and `_metrics` (RefNotFoundMetrics) attributes
    defined by the host class.
    """

    @property
    def metrics(self) -> RefNotFoundMetrics:
        """Get ref-failure statistics data."""
        return self._metrics

    def _get_context_refs(self, max_total: int = 15) -> list[dict[str, str]]:
        """Get a context summary of currently available refs.

        Returns a diverse sample of refs (grouped by role, preferring named refs).

        Args:
            max_total: Maximum number of refs to return.

        Returns:
            [{"ref": "e0", "role": "button", "name": "Submit"}, ...]
        """
        role_groups: dict[str, list[tuple[str, str]]] = defaultdict(list)
        for ref_id, info in self._refs.items():
            role_groups[info.role].append((ref_id, info.name))

        for role, refs_list in role_groups.items():
            role_groups[role] = sorted(refs_list, key=lambda x: (not x[1], x[0]))

        result: list[dict[str, str]] = []
        per_role = max(1, max_total // max(1, len(role_groups)))

        for role in sorted(role_groups.keys()):
            for ref_id, name in role_groups[role][:per_role]:
                if len(result) >= max_total:
                    return result
                result.append({"ref": ref_id, "role": role, "name": name})

        return result

    def _log_metrics_if_needed(self) -> None:
        """Periodically log failure-rate statistics (every 100 interactions)."""
        if self._metrics.total_interactions % 100 == 0 and self._metrics.total_failures > 0:
            logger.info(
                "Ref failure metrics: "
                f"global_rate={self._metrics.failure_rate:.1%}, "
                f"recent_rate={self._metrics.recent_failure_rate:.1%}, "
                f"total_failures={self._metrics.total_failures}/{self._metrics.total_interactions}, "
                f"top_failed_refs={self._metrics.top_failed_refs[:3]}, "
                f"top_failed_actions={self._metrics.top_failed_actions}"
            )
