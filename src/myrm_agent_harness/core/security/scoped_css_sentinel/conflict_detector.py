"""Concurrent Micro-Agent Style Patch Conflict Detection and Multi-Buffer Merging."""

from __future__ import annotations

from .css_rewriter import ScopedCssAstRewriter
from .types import (
    ConcurrentStylePatch,
    ConflictCheckResult,
)


class ConcurrentStyleConflictDetector:
    """Detects target component collisions across concurrent micro-agent patches and produces merged styles."""

    def __init__(self, rewriter: ScopedCssAstRewriter | None = None) -> None:
        self._rewriter = rewriter or ScopedCssAstRewriter()

    @property
    def rewriter(self) -> ScopedCssAstRewriter:
        """Access CSS AST rewriter."""
        return self._rewriter

    def check_and_merge_patches(
        self, patches: list[ConcurrentStylePatch]
    ) -> ConflictCheckResult:
        """Analyze concurrent style patches for target overlap and global selector violations.

        Returns:
            ConflictCheckResult indicating whether patches are orthogonal or conflicting,
            along with merged scoped CSS output if valid.
        """
        if not patches:
            return ConflictCheckResult(
                has_conflict=False,
                conflicting_agents=[],
                reason="No patches provided",
                merged_scoped_css="",
            )

        # 1. Check for target component collisions
        target_to_agents: dict[str, list[str]] = {}
        for p in patches:
            target = p.component_target_id.strip().lower()
            target_to_agents.setdefault(target, []).append(p.agent_id)

        conflicting_agents: list[str] = []
        for agents in target_to_agents.values():
            if len(agents) > 1:
                conflicting_agents.extend(agents)

        if conflicting_agents:
            unique_conflicts = sorted(set(conflicting_agents))
            return ConflictCheckResult(
                has_conflict=True,
                conflicting_agents=unique_conflicts,
                reason=(
                    f"Concurrent patch collision detected: multiple agents ({', '.join(unique_conflicts)}) "
                    "attempted to style the same target component simultaneously without coordination."
                ),
                merged_scoped_css=None,
            )

        # 2. Scope each patch and verify zero global root selector violations
        scoped_sections: list[str] = []
        for p in patches:
            res = self._rewriter.scope_css(p.css_content, p.component_target_id)
            if not res.is_valid:
                violation_reasons = "; ".join(v.reason for v in res.violations)
                return ConflictCheckResult(
                    has_conflict=True,
                    conflicting_agents=[p.agent_id],
                    reason=f"Agent '{p.agent_id}' submitted prohibited styles: {violation_reasons}",
                    merged_scoped_css=None,
                )

            scoped_sections.append(
                f"/* Agent: {p.agent_id} | Target: {p.component_target_id} */\n{res.scoped_css}"
            )

        # 3. All patches are orthogonal and safely scoped
        merged_css = "\n\n".join(scoped_sections)
        return ConflictCheckResult(
            has_conflict=False,
            conflicting_agents=[],
            reason="All concurrent style patches are orthogonal and successfully scoped.",
            merged_scoped_css=merged_css,
        )
