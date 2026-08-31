"""Auto-Approval Root Cause Attribution and Quota Decoupling Auditor.

[INPUT]
- myrm_agent_harness.observability.approval_audit.types::(
    ApprovalTriggerCategory,
    ApprovalTriggerEvent,
    AutoApprovalAuditReport,
    DualTrackQuotaBreakdown,
    TopOffenderItem,
  ) (POS: 自动审批审计类型定义)

[OUTPUT]
- AutoApprovalAuditor: Pure-rule normalization, bounded Top-Offenders clustering, and dual-track quota auditor

[POS]
Production-grade audit engine aggregating security review triggers, decoupling primary task costs from verification overhead, and deriving actionable allowlist rules.
"""

from __future__ import annotations

import logging
import os
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

logger = logging.getLogger(__name__)


class AutoApprovalAuditor:
    """Zero-LLM auditor analyzing auto-approval trigger causes and decoupling audit costs."""

    def __init__(
        self,
        *,
        max_tracked_offenders: int = 100,
        price_per_million_prompt: float = 2.5,
        price_per_million_completion: float = 10.0,
        price_per_million_cached: float = 0.5,
    ) -> None:
        self._max_tracked_offenders = max_tracked_offenders
        self._price_prompt = price_per_million_prompt
        self._price_completion = price_per_million_completion
        self._price_cached = price_per_million_cached

    def estimate_cost(self, prompt_tokens: int, completion_tokens: int, cached_prompt_tokens: int = 0) -> float:
        """Estimate USD financial cost for a single LLM verification step."""
        uncached_prompt = max(0, prompt_tokens - cached_prompt_tokens)
        cached_cost = (cached_prompt_tokens / 1_000_000.0) * self._price_cached
        uncached_cost = (uncached_prompt / 1_000_000.0) * self._price_prompt
        comp_cost = (completion_tokens / 1_000_000.0) * self._price_completion
        return round(cached_cost + uncached_cost + comp_cost, 6)

    def normalize_target(self, raw_target: str, category: ApprovalTriggerCategory) -> str:
        """Normalize raw intercepted target string into a clean, clusterable entity."""
        target = raw_target.strip()
        if not target:
            return "<empty_target>"

        if category == ApprovalTriggerCategory.FILE_BOUNDARY:
            # Normalize to directory prefix wildcard (e.g. '/var/log/app.log' -> '/var/log/*')
            try:
                norm = os.path.normpath(target)
                parent = os.path.dirname(norm)
                if parent == "" or parent == ".":
                    return "./*"
                if parent == "/":
                    return "/*"
                return f"{parent}/*"
            except Exception:
                return f"{target[:32]}/*"

        elif category == ApprovalTriggerCategory.NETWORK_DOMAIN:
            # Extract hostname/domain from URL
            try:
                # Handle URLs without scheme (e.g. 'api.github.com/v1')
                parse_target = target if "://" in target else f"https://{target}"
                parsed = urlsplit(parse_target)
                host = parsed.netloc.split(":")[0] if parsed.netloc else parsed.path.split("/")[0]
                return host.lower() if host else target[:64].lower()
            except Exception:
                return target[:64].lower()

        elif category == ApprovalTriggerCategory.COMMAND_EXECUTION:
            # Extract executable basename (e.g. 'rm -rf /tmp/foo' -> 'rm', '/usr/bin/git push' -> 'git')
            try:
                parts = shlex.split(target)
                if parts:
                    exe = os.path.basename(parts[0])
                    return exe.lower()
                return target.split()[0].lower() if target.split() else target[:32].lower()
            except Exception:
                return target.split()[0].lower() if target.split() else target[:32].lower()

        elif category == ApprovalTriggerCategory.TOOL_ELEVATION:
            # Extract tool namespace prefix if available (e.g. 'mcp__github__create_issue' -> 'mcp__github')
            if "__" in target:
                parts = target.split("__")
                return f"{parts[0]}__{parts[1]}"
            return target[:48]

        # UNKNOWN or fallback
        return target[:64]

    def suggest_allow_pattern(self, normalized_target: str, category: ApprovalTriggerCategory) -> str:
        """Derive an actionable minimal-privilege allowlist pattern for this normalized target."""
        if category == ApprovalTriggerCategory.FILE_BOUNDARY:
            return normalized_target  # already ends with /*

        elif category == ApprovalTriggerCategory.NETWORK_DOMAIN:
            if "." in normalized_target and not normalized_target.startswith("*."):
                return f"*.{normalized_target}"
            return normalized_target

        elif category == ApprovalTriggerCategory.COMMAND_EXECUTION:
            return f"{normalized_target} *"

        elif category == ApprovalTriggerCategory.TOOL_ELEVATION:
            return f"{normalized_target}::*"

        return f"allow:{normalized_target}"

    def record_trigger(
        self,
        *,
        session_id: str,
        raw_target: str,
        category: ApprovalTriggerCategory,
        tool_name: str,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        cached_prompt_tokens: int = 0,
        cost_usd: float | None = None,
    ) -> ApprovalTriggerEvent:
        """Create and return a normalized immutable ApprovalTriggerEvent."""
        norm_target = self.normalize_target(raw_target, category)
        calc_cost = (
            self.estimate_cost(prompt_tokens, completion_tokens, cached_prompt_tokens)
            if cost_usd is None
            else cost_usd
        )

        return ApprovalTriggerEvent(
            session_id=session_id,
            category=category,
            raw_target=raw_target,
            normalized_target=norm_target,
            tool_name=tool_name,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cached_prompt_tokens=cached_prompt_tokens,
            cost_usd=calc_cost,
        )

    def evaluate_events(
        self,
        events: Sequence[ApprovalTriggerEvent],
        *,
        session_id: str,
        main_task_rounds: int = 0,
        main_task_prompt_tokens: int = 0,
        main_task_completion_tokens: int = 0,
        main_task_cached_tokens: int = 0,
        main_task_cost_usd: float = 0.0,
    ) -> AutoApprovalAuditReport:
        """Aggregate approval events, compute dual-track quota metrics, and generate diagnostic report."""
        category_counts: dict[ApprovalTriggerCategory, int] = defaultdict(int)
        for cat in ApprovalTriggerCategory:
            category_counts[cat] = 0

        audit_prompt = 0
        audit_comp = 0
        audit_cached = 0
        audit_cost = 0.0

        # Target aggregation buckets: (category, total_tokens, total_cost, hit_count)
        target_hits: dict[str, list[object]] = {}

        for evt in events:
            category_counts[evt.category] += 1
            audit_prompt += evt.prompt_tokens
            audit_comp += evt.completion_tokens
            audit_cached += evt.cached_prompt_tokens
            audit_cost += evt.cost_usd

            key = evt.normalized_target
            if key not in target_hits:
                # [category, total_tokens, total_cost, hit_count]
                target_hits[key] = [evt.category, evt.total_tokens, evt.cost_usd, 1]
            else:
                entry = target_hits[key]
                entry[1] = int(entry[1]) + evt.total_tokens
                entry[2] = float(entry[2]) + evt.cost_usd
                entry[3] = int(entry[3]) + 1

        dual_track = DualTrackQuotaBreakdown(
            main_task_rounds=main_task_rounds,
            main_task_prompt_tokens=main_task_prompt_tokens,
            main_task_completion_tokens=main_task_completion_tokens,
            main_task_cached_tokens=main_task_cached_tokens,
            main_task_cost_usd=round(main_task_cost_usd, 6),
            audit_rounds=len(events),
            audit_prompt_tokens=audit_prompt,
            audit_completion_tokens=audit_comp,
            audit_cached_tokens=audit_cached,
            audit_cost_usd=round(audit_cost, 6),
        )

        # Build bounded Top-Offenders list sorted by hit_count descending
        sorted_targets = sorted(
            target_hits.items(),
            key=lambda item: int(item[1][3]),
            reverse=True,
        )[: self._max_tracked_offenders]

        top_offenders: list[TopOffenderItem] = []
        for norm_target, (cat_obj, tot_tokens, tot_cost, hit_count) in sorted_targets:
            cat = ApprovalTriggerCategory(cat_obj)
            top_offenders.append(
                TopOffenderItem(
                    normalized_target=norm_target,
                    category=cat,
                    hit_count=int(hit_count),
                    total_tokens=int(tot_tokens),
                    estimated_cost_usd=round(float(tot_cost), 6),
                    suggested_allow_pattern=self.suggest_allow_pattern(norm_target, cat),
                )
            )

        # Generate actionable diagnostic recommendations
        recommendations: list[str] = []
        if len(events) == 0:
            recommendations.append("Zero approval triggers recorded. Security boundary operating smoothly.")
        else:
            if dual_track.audit_cost_ratio >= 0.05 or dual_track.audit_token_ratio >= 0.05:
                recommendations.append(
                    f"Auto-review cost represents {dual_track.audit_cost_ratio:.1%} of total session spend. "
                    "Consider allowlisting frequent benign targets to reduce verification overhead."
                )

            high_frequency = [o for o in top_offenders if o.hit_count >= 2]
            if high_frequency:
                top_patterns = ", ".join(f"'{o.suggested_allow_pattern}'" for o in high_frequency[:3])
                recommendations.append(
                    f"Top repeat offender patterns ({top_patterns}) triggered multiple reviews. "
                    "Add these patterns to your project allowlist for 1-click bypass."
                )

        return AutoApprovalAuditReport(
            session_id=session_id,
            total_triggers=len(events),
            category_counts=dict(category_counts),
            dual_track_breakdown=dual_track,
            top_offenders=top_offenders,
            recommendations=recommendations,
        )
