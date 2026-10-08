"""Assembly Path Probe and Multi-Ingress Governance Matrix.

Inspects tool invocation pathways across:
1. INTERACTIVE_CHAT (Web / desktop user chat)
2. REST_API (Machine / webhook invocations)
3. SUBAGENT_DAG (Subagent team member delegations)
4. BACKGROUND_CRON (Scheduled background automations)

Validates 100% path coverage before releasing or merging.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Sequence

from myrm_agent_harness.core.security.governance_assembly.types import (
    GovernanceMatrixReport,
    IngressSource,
    ToolCallAssemblyTrace,
)


class GovernanceAssemblyProbe:
    """Probe recording and auditing governance wrappers on all tool invocation paths."""

    def __init__(self) -> None:
        self._traces: list[ToolCallAssemblyTrace] = []

    def record_invocation(
        self,
        tool_name: str,
        ingress_source: IngressSource,
        applied_middlewares: Sequence[str],
        is_governed: bool,
        bypassed_guards: Sequence[str] = (),
        call_stack_summary: str = "",
    ) -> ToolCallAssemblyTrace:
        """Record an observed tool invocation on the execution path."""
        trace_id = f"trc-{uuid.uuid4().hex[:10]}"
        trace = ToolCallAssemblyTrace(
            trace_id=trace_id,
            tool_name=tool_name,
            ingress_source=ingress_source,
            call_stack_summary=call_stack_summary or f"callpath::{ingress_source.value}::{tool_name}",
            applied_middlewares=tuple(applied_middlewares),
            is_governed=is_governed,
            bypassed_guards=tuple(bypassed_guards),
        )
        self._traces.append(trace)
        return trace

    def generate_matrix_report(self) -> GovernanceMatrixReport:
        """Calculate multi-ingress coverage matrix report."""
        total = len(self._traces)
        if total == 0:
            return GovernanceMatrixReport(
                total_invocations=0,
                governed_invocations=0,
                bypassed_invocations=0,
                coverage_ratio=1.0,
                is_fully_compliant=True,
                traces_by_ingress={},
                violations=(),
            )

        governed_count = sum(1 for t in self._traces if t.is_governed)
        bypassed_count = total - governed_count
        ratio = governed_count / total

        by_ingress: dict[str, int] = defaultdict(int)
        violations: list[str] = []

        for t in self._traces:
            by_ingress[t.ingress_source.value] += 1
            if not t.is_governed:
                violations.append(
                    f"Path violation on [{t.ingress_source.value}] for tool '{t.tool_name}': "
                    f"missing {list(t.bypassed_guards)}"
                )

        return GovernanceMatrixReport(
            total_invocations=total,
            governed_invocations=governed_count,
            bypassed_invocations=bypassed_count,
            coverage_ratio=round(ratio, 4),
            is_fully_compliant=(bypassed_count == 0),
            traces_by_ingress=dict(by_ingress),
            violations=tuple(violations),
        )

    def clear(self) -> None:
        """Reset all recorded traces."""
        self._traces.clear()
