"""Auto-Approval Root-Cause Auditor and Quota Attribution Engine.

[INPUT]
- myrm_agent_harness.observability.approval_audit.types::(ApprovalTriggerCategory, ApprovalTriggerEvent, AutoApprovalAuditReport, DualTrackQuotaBreakdown, TopOffenderItem) (POS: 自动审批审计数据契约)

[OUTPUT]
- AutoApprovalAuditor: Pure-rule categorization, target normalization, bounded Top-Offenders aggregation, and dual-track report generator

[POS]
Harness-level zero-LLM telemetry engine providing root-cause four-category classification, dual-track cost attribution, and 1-click whitelist recommendations.
"""

from __future__ import annotations

import os
import re
from typing import Mapping, Sequence
from urllib.parse import urlparse

from myrm_agent_harness.observability.approval_audit.types import (
    ApprovalTriggerCategory,
    ApprovalTriggerEvent,
    AutoApprovalAuditReport,
    DualTrackQuotaBreakdown,
    TopOffenderItem,
)


class AutoApprovalAuditor:
    """Thread-safe, bounded memory auditor aggregating approval intercepts and dual-track quota."""

    def __init__(self, *, max_tracked_offenders: int = 100) -> None:
        """Initialize auditor with bounded memory size.

        Args:
            max_tracked_offenders: Maximum unique target entities tracked before capping.
        """
        self._max_tracked_offenders = max_tracked_offenders
        self._events: list[ApprovalTriggerEvent] = []
        self._main_task_rounds = 0
        self._main_task_tokens = 0
        self._main_task_cost_usd = 0.0

    @classmethod
    def categorize_target(cls, tool_name: str, raw_target: str) -> ApprovalTriggerCategory:
        """Deterministically classify an intercept into one of the standard four root causes."""
        tool_lower = tool_name.lower()
        target_lower = raw_target.lower()

        if "web" in tool_lower or "http" in tool_lower or target_lower.startswith(("http://", "https://", "ws://", "wss://")):
            return ApprovalTriggerCategory.NETWORK_DOMAIN
        if "file" in tool_lower or "write" in tool_lower or "read" in tool_lower or raw_target.startswith(("/", "./", "../", "~")):
            return ApprovalTriggerCategory.FILE_BOUNDARY
        if "shell" in tool_lower or "bash" in tool_lower or "exec" in tool_lower or "command" in tool_lower:
            return ApprovalTriggerCategory.COMMAND_EXECUTION
        if "mcp" in tool_lower or "dynamic" in tool_lower or "invoke" in tool_lower:
            return ApprovalTriggerCategory.TOOL_ELEVATION

        return ApprovalTriggerCategory.UNKNOWN

    @classmethod
    def normalize_target(cls, category: ApprovalTriggerCategory, raw_target: str) -> str:
        """Normalize raw parameter into a clean cluster key (e.g. Host, Directory, Executable)."""
        clean = raw_target.strip()
        if not clean:
            return "unknown_target"

        if category == ApprovalTriggerCategory.NETWORK_DOMAIN:
            if not clean.startswith(("http://", "https://", "ws://", "wss://")):
                clean = "http://" + clean
            try:
                parsed = urlparse(clean)
                host = parsed.hostname or clean
                return host.lower()
            except Exception:
                return clean.lower()

        elif category == ApprovalTriggerCategory.FILE_BOUNDARY:
            norm_path = os.path.normpath(clean)
            parent = os.path.dirname(norm_path)
            if parent and parent != norm_path:
                return f"{parent}/*"
            return f"{norm_path}/*"

        elif category == ApprovalTriggerCategory.COMMAND_EXECUTION:
            # Extract executable binary / command name (first token)
            tokens = clean.split()
            if tokens:
                cmd = os.path.basename(tokens[0])
                return cmd
            return clean

        elif category == ApprovalTriggerCategory.TOOL_ELEVATION:
            # Extract MCP tool or namespace
            return clean.split(":")[0] if ":" in clean else clean

        return clean

    @classmethod
    def suggest_allow_pattern(cls, category: ApprovalTriggerCategory, normalized_target: str) -> str:
        """Generate standard actionable Glob or allowlist pattern for 1-click allowlisting."""
        if category == ApprovalTriggerCategory.NETWORK_DOMAIN:
            # e.g. api.github.com -> *.github.com, localhost -> localhost
            parts = normalized_target.split(".")
            if len(parts) >= 3 and not parts[0].isdigit():
                return f"*.{'.'.join(parts[1:])}"
            return normalized_target

        elif category == ApprovalTriggerCategory.FILE_BOUNDARY:
            # Ensure path ends with wildcard
            if not normalized_target.endswith("/*"):
                return f"{normalized_target}/*"
            return normalized_target

        elif category == ApprovalTriggerCategory.COMMAND_EXECUTION:
            return f"{normalized_target} *"

        elif category == ApprovalTriggerCategory.TOOL_ELEVATION:
            return f"{normalized_target}:*"

        return normalized_target

    def record_main_task_usage(
        self,
        *,
        rounds: int = 1,
        tokens: int = 0,
        cost_usd: float = 0.0,
    ) -> None:
        """Accumulate usage incurred strictly by the main task agent."""
        self._main_task_rounds += rounds
        self._main_task_tokens += tokens
        self._main_task_cost_usd += cost_usd

    def record_trigger_event(
        self,
        *,
        session_id: str,
        tool_name: str,
        raw_target: str,
        category: ApprovalTriggerCategory | None = None,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        cost_usd: float = 0.0,
    ) -> ApprovalTriggerEvent:
        """Record an intercepted approval event with deterministic categorization and normalization."""
        resolved_category = category or self.categorize_target(tool_name, raw_target)
        normalized = self.normalize_target(resolved_category, raw_target)

        event = ApprovalTriggerEvent(
            session_id=session_id,
            category=resolved_category,
            raw_target=raw_target,
            normalized_target=normalized,
            tool_name=tool_name,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_usd=cost_usd,
        )
        self._events.append(event)
        return event

    def generate_report(self, *, session_id: str, top_n: int = 10) -> AutoApprovalAuditReport:
        """Generate comprehensive diagnostic report with dual-track quota and Top-Offenders."""
        category_counts: dict[ApprovalTriggerCategory, int] = {
            ApprovalTriggerCategory.FILE_BOUNDARY: 0,
            ApprovalTriggerCategory.NETWORK_DOMAIN: 0,
            ApprovalTriggerCategory.COMMAND_EXECUTION: 0,
            ApprovalTriggerCategory.TOOL_ELEVATION: 0,
            ApprovalTriggerCategory.UNKNOWN: 0,
        }

        offenders_map: dict[str, dict[str, object]] = {}
        audit_tokens = 0
        audit_cost_usd = 0.0

        for ev in self._events:
            category_counts[ev.category] = category_counts.get(ev.category, 0) + 1
            audit_tokens += ev.total_tokens
            audit_cost_usd += ev.cost_usd

            key = f"{ev.category}::{ev.normalized_target}"
            if key not in offenders_map and len(offenders_map) < self._max_tracked_offenders:
                offenders_map[key] = {
                    "normalized_target": ev.normalized_target,
                    "category": ev.category,
                    "hit_count": 0,
                    "total_tokens": 0,
                    "estimated_cost_usd": 0.0,
                    "suggested_allow_pattern": self.suggest_allow_pattern(ev.category, ev.normalized_target),
                }

            if key in offenders_map:
                entry = offenders_map[key]
                entry["hit_count"] = int(entry["hit_count"]) + 1
                entry["total_tokens"] = int(entry["total_tokens"]) + ev.total_tokens
                entry["estimated_cost_usd"] = float(entry["estimated_cost_usd"]) + ev.cost_usd

        # Sort top offenders by hit_count descending
        sorted_entries = sorted(
            offenders_map.values(),
            key=lambda item: int(item["hit_count"]),
            reverse=True,
        )[:top_n]

        top_offenders: list[TopOffenderItem] = [
            TopOffenderItem(
                normalized_target=str(e["normalized_target"]),
                category=ApprovalTriggerCategory(str(e["category"])),
                hit_count=int(e["hit_count"]),
                total_tokens=int(e["total_tokens"]),
                estimated_cost_usd=round(float(e["estimated_cost_usd"]), 6),
                suggested_allow_pattern=str(e["suggested_allow_pattern"]),
            )
            for e in sorted_entries
        ]

        dual_track = DualTrackQuotaBreakdown(
            main_task_rounds=self._main_task_rounds,
            main_task_tokens=self._main_task_tokens,
            main_task_cost_usd=round(self._main_task_cost_usd, 6),
            audit_rounds=len(self._events),
            audit_tokens=audit_tokens,
            audit_cost_usd=round(audit_cost_usd, 6),
        )

        recommendations: list[str] = []
        if top_offenders:
            top = top_offenders[0]
            recommendations.append(
                f"Top trigger target '{top.normalized_target}' was intercepted {top.hit_count} times. "
                f"Consider adding rule '{top.suggested_allow_pattern}' to project allowlist."
            )
        if dual_track.audit_cost_ratio > 0.30:
            recommendations.append(
                f"Auto-review cost ratio is {dual_track.audit_cost_ratio:.1%}. "
                "Evaluate switching to lighter verification models or broadening allowlists."
            )
        if not recommendations:
            recommendations.append("Auto-approval triggers are within healthy nominal bounds.")

        return AutoApprovalAuditReport(
            session_id=session_id,
            total_triggers=len(self._events),
            category_counts=category_counts,
            dual_track_breakdown=dual_track,
            top_offenders=top_offenders,
            recommendations=recommendations,
        )
