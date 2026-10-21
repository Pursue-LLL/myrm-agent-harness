"""
[INPUT]: Inbound HTTP request paths, fallback event labels, and metric cardinality boundaries.
[OUTPUT]: High-performance governor enforcing cardinality caps on hot-path metrics and diverting overflowing labels to sentinel buckets.
[POS]: myrm-agent-harness/src/myrm_agent_harness/observability/cardinality_cap/governor.py
"""

import re
from typing import Dict, List, Optional, Set, Tuple
from myrm_agent_harness.observability.cardinality_cap.models import (
    CardinalityCapConfig,
    CardinalityStatus,
    MetricCardinalityStat,
)

_UUID_OR_ID_PATTERN = re.compile(
    r"(?:[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}|\b\d+\b|[0-9a-fA-F]{16,})"
)


class MetricCardinalityGovernor:
    """Safeguard preventing cardinality explosion in hot-path metrics collectors."""

    def __init__(self, config: Optional[CardinalityCapConfig] = None) -> None:
        self.config = config or CardinalityCapConfig()
        self._metric_caps: Dict[str, int] = {}
        self._tracked_labels: Dict[str, Set[str]] = {}
        self._label_hits: Dict[str, Dict[str, int]] = {}
        self._overflow_counts: Dict[str, int] = {}
        self._total_samples: Dict[str, int] = {}

    def reset(self) -> None:
        """Clear all metric tracking state."""
        self._metric_caps.clear()
        self._tracked_labels.clear()
        self._label_hits.clear()
        self._overflow_counts.clear()
        self._total_samples.clear()

    def configure_cap(self, metric_name: str, cap_limit: int) -> None:
        """Explicitly set maximum unique labels for a target metric."""
        if cap_limit < 1:
            cap_limit = 1
        self._metric_caps[metric_name] = cap_limit

    def normalize_path(self, path: str) -> str:
        """Normalize dynamic IDs/UUIDs in request paths into static parameterized placeholders."""
        # Replace variable ID segments
        normalized = _UUID_OR_ID_PATTERN.sub("{id}", path)
        return normalized

    def normalize_or_cap(self, metric_name: str, label_value: str) -> Tuple[str, bool]:
        """Resolve a label under cardinality cap guardrails.

        Returns:
            Tuple[resolved_label, is_overflow]: The safe label string and boolean flag.
        """
        # 1. Path normalization if the label looks like an endpoint path
        clean_label = self.normalize_path(label_value) if "/" in label_value else label_value

        cap = self._metric_caps.get(metric_name, self.config.default_cap)
        tracked = self._tracked_labels.setdefault(metric_name, set())
        hits = self._label_hits.setdefault(metric_name, {})
        self._total_samples[metric_name] = self._total_samples.get(metric_name, 0) + 1

        # 2. Check if clean_label is in allowlisted paths or already tracked
        if clean_label in self.config.opt_in_paths or clean_label in tracked:
            tracked.add(clean_label)
            hits[clean_label] = hits.get(clean_label, 0) + 1
            return clean_label, False

        # 3. New unseen label - check cap limit
        if len(tracked) < cap:
            tracked.add(clean_label)
            hits[clean_label] = hits.get(clean_label, 0) + 1
            return clean_label, False

        # 4. Cap exceeded - divert to overflow sentinel
        overflow_sentinel = self.config.overflow_sentinel
        self._overflow_counts[metric_name] = self._overflow_counts.get(metric_name, 0) + 1
        hits[overflow_sentinel] = hits.get(overflow_sentinel, 0) + 1
        return overflow_sentinel, True

    def get_metric_stats(self, metric_name: Optional[str] = None) -> List[MetricCardinalityStat]:
        """Retrieve cardinality utilization, status, and overflow tallies."""
        results: List[MetricCardinalityStat] = []
        target_names = [metric_name] if metric_name else list(self._total_samples.keys())

        for name in target_names:
            cap = self._metric_caps.get(name, self.config.default_cap)
            tracked_set = self._tracked_labels.get(name, set())
            tracked_count = len(tracked_set)
            overflow_count = self._overflow_counts.get(name, 0)
            total_samples = self._total_samples.get(name, 0)
            hits = self._label_hits.get(name, {})

            utilization = round((tracked_count / cap * 100.0), 1) if cap > 0 else 0.0

            if overflow_count > 0 or tracked_count >= cap:
                status = CardinalityStatus.OVERFLOWING
            elif tracked_count >= cap * self.config.warning_threshold:
                status = CardinalityStatus.APPROACHING_CAP
            else:
                status = CardinalityStatus.HEALTHY

            # Sort top labels by hit count
            top_labels = sorted(hits.keys(), key=lambda k: hits[k], reverse=True)[:10]

            results.append(
                MetricCardinalityStat(
                    metric_name=name,
                    cap_limit=cap,
                    tracked_cardinality=tracked_count,
                    overflow_count=overflow_count,
                    total_samples=total_samples,
                    utilization_pct=utilization,
                    status=status,
                    top_tracked_labels=top_labels,
                    label_hits=hits,
                )
            )

        return results
