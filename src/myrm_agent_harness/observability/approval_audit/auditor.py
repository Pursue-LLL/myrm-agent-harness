"""Auto-Approval Root Cause Diagnostic and Quota Attribution Auditor.

[INPUT]
- myrm_agent_harness.observability.approval_audit.types::(
    ApprovalTriggerCategory,
    ApprovalTriggerEvent,
    TopOffenderItem,
    DualTrackQuotaBreakdown,
    AutoApprovalAuditReport,
  ) (POS: 审计数据基础契约)

[OUTPUT]
- AutoApprovalAuditor: Aggregation engine for trigger normalization, top offenders ranking, and quota attribution

[POS]
Harness-level pure-rule observability engine analyzing security approval triggers and cost attribution.
"""

from __future__ import annotations

import os
import re
import shlex
from collections import defaultdict
from typing import Sequence
from urllib.parse import urlsplit

from myrm_agent_harness.observability.approval_audit.types import (
    ApprovalTriggerCategory,
    ApprovalTriggerEvent,
    AutoApprovalAuditReport,
    DualTrackQuotaBreakdown,
    TopOffenderItem,
)


class AutoApprovalAuditor:
    """Pure-rule auditor analyzing auto-approval causes, top offenders, and dual-track quotas."""

    def __init__(self, *, max_tracked_offenders: int = 100) -> None:
        """Initialize auditor with bounded memory tracking limit.

        Args:
            max_tracked_offenders: Maximum distinct targets to retain in memory ranking.
        """
        self._max_tracked_offenders = max(10, max_tracked_offenders)

    @classmethod
    def normalize_target(cls, category: ApprovalTriggerCategory, raw_target: str) -> str:
        """Normalize raw target parameter to a clean cluster key."""
        target = raw_target.strip()
        if not target:
            return "unknown"

        if category == ApprovalTriggerCategory.NETWORK_DOMAIN:
            # Parse URL host or domain
            try:
                # Add scheme if missing to allow urlsplit to parse netloc
                if not target.startswith(("http://", "https://", "ws://", "wss://")):
                    target_with_scheme = f"https://{target}"
                else:
                    target_with_scheme = target
                parsed = urlsplit(target_with_scheme)
                host = (parsed.hostname or parsed.netloc).lower()
                return host if host else target[:64]
            except Exception:
                return target[:64]

        elif category == ApprovalTriggerCategory.FILE_BOUNDARY:
            # Extract normalized parent directory or file path
            try:
                norm_path = os.path.normpath(target)
                if os.path.isdir(norm_path) or target.endswith(("/", "\\")):
                    return f"{norm_path}/*"
                parent_dir = os.path.dirname(norm_path)
                return f"{parent_dir}/*" if parent_dir and parent_dir != "." else norm_path
            except Exception:
                return target[:64]

        elif category == ApprovalTriggerCategory.COMMAND_EXECUTION:
            # Extract executable command binary name
            try:
                parts = shlex.split(target)
                if parts:
                    binary_name = os.path.basename(parts[0])
                    return binary_name
            except Exception:
                pass
            match = re.match(r"^([a-zA-Z0-9_\-\.]+)", target)
            return match.group(1) if match else target[:32]

        elif category == ApprovalTriggerCategory.TOOL_ELEVATION:
            # Tool name or namespace
            return target.split("(")[0].strip()[:48]

        return target[:64]

    @classmethod
    def suggest_allow_pattern(cls, category: ApprovalTriggerCategory, normalized_target: str) -> str:
        """Derive actionable, minimal-privilege allowlist pattern from normalized target."""
        if category == ApprovalTriggerCategory.NETWORK_DOMAIN:
            # If domain has >= 2 dots (e.g. sub.example.com), suggest wildcard domain
            parts = normalized_target.split(".")
            if len(parts) >= 3:
                root_domain = ".".join(parts[-2:])
                return f"*.{root_domain}"
            return normalized_target

        elif category == ApprovalTriggerCategory.FILE_BOUNDARY:
            if not normalized_target.endswith("*"):
                return f"{normalized_target}/*"
            return normalized_target

        elif category == ApprovalTriggerCategory.COMMAND_EXECUTION:
            return f"{normalized_target} *"

        elif category == ApprovalTriggerCategory.TOOL_ELEVATION:
            return f"{normalized_target}:allow"

        return normalized_target

    def evaluate_audit_report(
        self,
        events: Sequence[ApprovalTriggerEvent],
        *,
        session_id: str,
        dual_track: DualTrackQuotaBreakdown | None = None,
    ) -> AutoApprovalAuditReport:
        """Evaluate a sequence of trigger events and produce a structured diagnostic report."""
        if not events and dual_track is None:
            return AutoApprovalAuditReport(
                session_id=session_id,
                total_triggers=0,
                category_counts={cat: 0 for cat in ApprovalTriggerCategory},
                dual_track_breakdown=DualTrackQuotaBreakdown(),
                top_offenders=[],
                recommendations=["No security approval triggers recorded."],
            )

        category_counts: dict[ApprovalTriggerCategory, int] = defaultdict(int)
        for cat in ApprovalTriggerCategory:
            category_counts[cat] = 0

        # Cluster by (category, normalized_target)
        clusters: dict[tuple[ApprovalTriggerCategory, str], dict[str, float | int]] = defaultdict(
            lambda: {"hits": 0, "tokens": 0, "cost": 0.0}
        )

        audit_rounds_from_events = 0
        audit_tokens_from_events = 0
        audit_cost_from_events = 0.0

        for event in events:
            category_counts[event.category] += 1
            key = (event.category, event.normalized_target)
            clusters[key]["hits"] += 1
            clusters[key]["tokens"] += event.total_tokens
            clusters[key]["cost"] += event.cost_usd

            if event.is_audit_agent:
                audit_rounds_from_events += 1
                audit_tokens_from_events += event.total_tokens
                audit_cost_from_events += event.cost_usd

        # Build TopOffenderItem list
        offenders: list[TopOffenderItem] = []
        for (cat, norm_target), stats in clusters.items():
            pattern = self.suggest_allow_pattern(cat, norm_target)
            offenders.append(
                TopOffenderItem(
                    normalized_target=norm_target,
                    category=cat,
                    hit_count=int(stats["hits"]),
                    total_tokens=int(stats["tokens"]),
                    estimated_cost_usd=round(float(stats["cost"]), 6),
                    suggested_allow_pattern=pattern,
                )
            )

        # Sort by hit_count descending, cost descending, token descending
        offenders.sort(key=lambda item: (item.hit_count, item.estimated_cost_usd, item.total_tokens), reverse=True)
        bounded_offenders = offenders[: self._max_tracked_offenders]

        # Consolidate dual-track breakdown
        final_dual_track: DualTrackQuotaBreakdown
        if dual_track is not None:
            final_dual_track = dual_track
        else:
            final_dual_track = DualTrackQuotaBreakdown(
                audit_agent_rounds=audit_rounds_from_events,
                audit_agent_prompt_tokens=audit_tokens_from_events,
                audit_agent_cost_usd=round(audit_cost_from_events, 6),
            )

        # Generate recommendations
        recommendations: list[str] = []
        if len(events) == 0:
            recommendations.append("No security approval triggers recorded in this evaluation window.")
        else:
            if final_dual_track.audit_cost_ratio >= 0.30:
                recommendations.append(
                    f"Auto-review cost ratio is high ({final_dual_track.audit_cost_ratio:.1%}). "
                    f"Consider whitelisting frequent targets to reduce auxiliary review invocations."
                )

            # Highlight top offender if significant
            if bounded_offenders and bounded_offenders[0].hit_count >= 3:
                top = bounded_offenders[0]
                recommendations.append(
                    f"Frequent trigger on '{top.normalized_target}' ({top.hit_count} hits, category: {top.category}). "
                    f"Suggested allow pattern: `{top.suggested_allow_pattern}`."
                )

            # Highlight dominant category
            dominant_category = max(category_counts.items(), key=lambda x: x[1])
            if dominant_category[1] > 0:
                recommendations.append(
                    f"Primary approval trigger root cause: {dominant_category[0]} ({dominant_category[1]} event(s))."
                )

        return AutoApprovalAuditReport(
            session_id=session_id,
            total_triggers=len(events),
            category_counts=dict(category_counts),
            dual_track_breakdown=final_dual_track,
            top_offenders=bounded_offenders,
            recommendations=recommendations,
        )
