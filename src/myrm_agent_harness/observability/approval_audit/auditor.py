"""Auto-Approval Trigger Root-Cause Auditor and Dual-Track Usage Disaggregator.

[INPUT]
- myrm_agent_harness.observability.approval_audit.types::(
    ApprovalTriggerCategory,
    ApprovalTriggerEvent,
    AutoApprovalAuditReport,
    DualTrackQuotaBreakdown,
    TopOffenderItem,
  ) (POS: 审批归因与双轨解耦契约)

[OUTPUT]
- AutoApprovalAuditor: Pure-rule normalization, bounded top-offender aggregation, and audit report generator

[POS]
Harness-level zero-LLM telemetry engine providing deterministic 4-category trigger attribution and dual-track cost transparency.
"""

from __future__ import annotations

import os
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
    """Pure-rule auditor categorizing triggers, tracking top violators, and disaggregating quota."""

    def __init__(
        self,
        *,
        max_tracked_offenders: int = 100,
        price_per_million_prompt: float = 2.5,
        price_per_million_completion: float = 10.0,
    ) -> None:
        """Initialize auditor parameters.

        Args:
            max_tracked_offenders: Maximum number of unique offenders to retain in memory.
            price_per_million_prompt: Estimated cost per 1M prompt tokens (default USD 2.5).
            price_per_million_completion: Estimated cost per 1M completion tokens (default USD 10.0).
        """
        self._max_tracked_offenders = max_tracked_offenders
        self._price_prompt = price_per_million_prompt
        self._price_completion = price_per_million_completion

    @staticmethod
    def classify_and_normalize(
        raw_target: str,
        tool_name: str = "",
    ) -> tuple[ApprovalTriggerCategory, str, str]:
        """Classify trigger root cause and normalize target to a clusterable string.

        Returns:
            (category, normalized_target, suggested_allow_pattern)
        """
        target = raw_target.strip()
        tool_lower = tool_name.lower()

        # 1. Network / URL detection
        if (
            target.startswith(("http://", "https://", "ws://", "wss://"))
            or "fetch" in tool_lower
            or "curl" in tool_lower
        ):
            try:
                parsed = urlsplit(target if "://" in target else f"https://{target}")
                domain = parsed.hostname or target.split("/")[0]
                return (
                    ApprovalTriggerCategory.NETWORK_DOMAIN,
                    domain,
                    f"*.{domain}" if not domain.startswith("*.") else domain,
                )
            except Exception:
                pass

        # 2. File Boundary detection (absolute or relative file paths)
        if (
            target.startswith(("/", "~", "./", "../"))
            or "\\" in target
            or "file" in tool_lower
            or "write" in tool_lower
        ):
            # Extract parent directory prefix
            norm_path = os.path.normpath(target)
            parent_dir = os.path.dirname(norm_path) or norm_path
            suggested_pattern = (
                f"{parent_dir}/*" if not parent_dir.endswith("/*") else parent_dir
            )
            return (
                ApprovalTriggerCategory.FILE_BOUNDARY,
                parent_dir,
                suggested_pattern,
            )

        # 3. Shell / Command execution
        if (
            "bash" in tool_lower
            or "shell" in tool_lower
            or "exec" in tool_lower
            or any(
                target.startswith(cmd)
                for cmd in (
                    "git ",
                    "npm ",
                    "pytest ",
                    "rm ",
                    "docker ",
                    "python ",
                    "sh ",
                )
            )
        ):
            cmd_base = target.split()[0] if target else "command"
            return (
                ApprovalTriggerCategory.COMMAND_EXECUTION,
                cmd_base,
                f"{cmd_base} *",
            )

        # 4. Tool elevation / High-risk tool calls
        if (
            "mcp" in tool_lower
            or "admin" in tool_lower
            or "eval" in tool_lower
            or "delete" in tool_lower
        ):
            return (
                ApprovalTriggerCategory.TOOL_ELEVATION,
                tool_name or "mcp_tool",
                f"{tool_name}:*",
            )

        # Fallback unknown
        safe_preview = (target[:32] + "...") if len(target) > 32 else target
        return (
            ApprovalTriggerCategory.UNKNOWN,
            safe_preview or "unknown_target",
            f"{safe_preview}:*",
        )

    def estimate_event_cost(self, prompt_tokens: int, completion_tokens: int) -> float:
        """Calculate estimated financial cost in USD for a review step."""
        p_cost = (max(0, prompt_tokens) / 1_000_000.0) * self._price_prompt
        c_cost = (max(0, completion_tokens) / 1_000_000.0) * self._price_completion
        return round(p_cost + c_cost, 6)

    def generate_report(
        self,
        events: Sequence[ApprovalTriggerEvent],
        *,
        session_id: str,
        main_task_rounds: int = 0,
        main_task_tokens: int = 0,
        main_task_cost_usd: float = 0.0,
    ) -> AutoApprovalAuditReport:
        """Aggregate approval events and generate a diagnostic report with dual-track attribution."""
        if not events:
            return AutoApprovalAuditReport(
                session_id=session_id,
                total_triggers=0,
                category_counts={},
                dual_track_breakdown=DualTrackQuotaBreakdown(
                    main_task_rounds=main_task_rounds,
                    main_task_tokens=main_task_tokens,
                    main_task_cost_usd=round(main_task_cost_usd, 6),
                ),
                top_offenders=[],
                recommendations=["No auto-approval triggers observed in this session."],
            )

        category_counts: dict[str, int] = defaultdict(int)
        offender_hits: dict[str, int] = defaultdict(int)
        offender_tokens: dict[str, int] = defaultdict(int)
        offender_costs: dict[str, float] = defaultdict(float)
        offender_categories: dict[str, ApprovalTriggerCategory] = {}
        offender_patterns: dict[str, str] = {}

        total_audit_tokens = 0
        total_audit_cost = 0.0

        for ev in events:
            cat_str = str(ev.category)
            category_counts[cat_str] += 1

            t_tokens = ev.total_tokens
            ev_cost = (
                ev.cost_usd
                if ev.cost_usd > 0.0
                else self.estimate_event_cost(ev.prompt_tokens, ev.completion_tokens)
            )

            total_audit_tokens += t_tokens
            total_audit_cost += ev_cost

            # Group by normalized target with bounded eviction
            norm_key = ev.normalized_target
            if (
                len(offender_hits) < self._max_tracked_offenders
                or norm_key in offender_hits
            ):
                offender_hits[norm_key] += 1
                offender_tokens[norm_key] += t_tokens
                offender_costs[norm_key] = round(offender_costs[norm_key] + ev_cost, 6)
                offender_categories[norm_key] = ev.category
                if norm_key not in offender_patterns:
                    _, _, pattern = self.classify_and_normalize(
                        ev.raw_target, ev.tool_name
                    )
                    offender_patterns[norm_key] = pattern

        # Build sorted Top-Offenders list
        sorted_keys = sorted(
            offender_hits.keys(), key=lambda k: offender_hits[k], reverse=True
        )[:10]
        top_offenders: list[TopOffenderItem] = [
            TopOffenderItem(
                normalized_target=k,
                category=offender_categories[k],
                hit_count=offender_hits[k],
                total_tokens=offender_tokens[k],
                estimated_cost_usd=round(offender_costs[k], 6),
                suggested_allow_pattern=offender_patterns.get(k, f"{k}*"),
            )
            for k in sorted_keys
        ]

        dual_track = DualTrackQuotaBreakdown(
            main_task_rounds=main_task_rounds,
            main_task_tokens=main_task_tokens,
            main_task_cost_usd=round(main_task_cost_usd, 6),
            audit_rounds=len(events),
            audit_tokens=total_audit_tokens,
            audit_cost_usd=round(total_audit_cost, 6),
        )

        recommendations: list[str] = []
        if dual_track.audit_cost_ratio >= 0.30:
            recommendations.append(
                f"Safety audits accounted for {dual_track.audit_cost_ratio:.1%} of total session cost. "
                "Consider allowlisting recurring safe directories or domains."
            )

        if top_offenders:
            top = top_offenders[0]
            recommendations.append(
                f"Top offender '{top.normalized_target}' triggered {top.hit_count} approvals. "
                f"Suggested allowlist pattern: `{top.suggested_allow_pattern}`."
            )

        return AutoApprovalAuditReport(
            session_id=session_id,
            total_triggers=len(events),
            category_counts=dict(category_counts),
            dual_track_breakdown=dual_track,
            top_offenders=top_offenders,
            recommendations=recommendations,
        )
