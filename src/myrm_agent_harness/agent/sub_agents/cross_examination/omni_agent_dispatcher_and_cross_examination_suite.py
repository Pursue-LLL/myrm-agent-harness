"""Unified omni-agent single entry dispatcher and split cross-examination suite facade.

[INPUT]
- ConsensusDeltaHighlighter, OneClickArbitrator, SplitCrossExaminationEngine, UnifiedIntentDispatcher: Core engines.
- AdoptionChoice, AdoptionReceipt, AgentRoleTarget, CrossExamArbitrationReport, IntentRoutingDecision: Contract models.

[OUTPUT]
- OmniAgentUnifiedDispatcherAndSplitCrossExaminationSuite: Unified facade for Item 314.
- OmniAgentDispatcherSuite: Convenient alias.

[POS]
Main entry facade coordinating intelligent intent dispatch, concurrent multi-agent cross-examination, and one-click adoption.
"""

from __future__ import annotations

from typing import Callable, Mapping, Sequence

from .consensus_delta_highlighter import ConsensusDeltaHighlighter
from .cross_exam_types import (
    AdoptionChoice,
    AdoptionReceipt,
    AgentRoleTarget,
    CrossExamArbitrationReport,
    IntentRoutingDecision,
)
from .one_click_arbitrator import OneClickArbitrator
from .split_cross_examination_engine import SplitCrossExaminationEngine
from .unified_intent_dispatcher import UnifiedIntentDispatcher


class OmniAgentUnifiedDispatcherAndSplitCrossExaminationSuite:
    """Unified entry point resolving multi-agent fragmentation, tab switching, and consensus arbitration."""

    def __init__(self) -> None:
        self._dispatcher = UnifiedIntentDispatcher()
        self._highlighter = ConsensusDeltaHighlighter()
        self._engine = SplitCrossExaminationEngine(self._highlighter)
        self._arbitrator = OneClickArbitrator()

    def dispatch_query(self, query: str) -> IntentRoutingDecision:
        """Route user query to optimal primary agent and determine if multi-agent cross-examination is recommended."""
        return self._dispatcher.route_intent(query)

    def run_cross_examination(
        self,
        query: str,
        target_roles: Sequence[AgentRoleTarget] | None = None,
        custom_executors: Mapping[AgentRoleTarget, Callable[[str], str]] | None = None,
    ) -> CrossExamArbitrationReport:
        """Execute split cross-examination across candidate agents and synthesize agreements and divergences."""
        if target_roles is None:
            decision = self.dispatch_query(query)
            target_roles = decision.suggested_cross_exam_agents

        return self._engine.conduct_cross_examination(
            query=query,
            target_roles=target_roles,
            custom_executors=custom_executors,
        )

    def render_dashboard(self, report: CrossExamArbitrationReport) -> str:
        """Render high-signal Markdown cross-examination dashboard with common ground and critical deltas."""
        return self._highlighter.render_consensus_dashboard(report)

    def adopt_verdict(
        self,
        report: CrossExamArbitrationReport,
        choice: AdoptionChoice = AdoptionChoice.SYNTHESIZED_CONSENSUS,
        specific_agent_role: AgentRoleTarget | None = None,
    ) -> AdoptionReceipt:
        """Adopt final verdict and prepare structured context block for injection into workspace memory."""
        return self._arbitrator.adopt_verdict(
            report=report,
            choice=choice,
            specific_agent_role=specific_agent_role,
        )


OmniAgentDispatcherSuite = OmniAgentUnifiedDispatcherAndSplitCrossExaminationSuite
