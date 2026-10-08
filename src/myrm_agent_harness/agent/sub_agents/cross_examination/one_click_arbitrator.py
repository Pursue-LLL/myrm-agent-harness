# [INPUT]: AdoptionChoice, AdoptionReceipt, AgentRoleTarget, CrossExamArbitrationReport
# [OUTPUT]: OneClickArbitrator
# [POS]: agent/sub_agents/cross_examination/one_click_arbitrator.py

"""One-click arbitrator allowing adoption of specific agent outcomes or synthesized cross-exam consensus.

[INPUT]
- AdoptionChoice, AdoptionReceipt, AgentRoleTarget, CrossExamArbitrationReport: Models.

[OUTPUT]
- OneClickArbitrator: Processes user decision and compiles structured workspace context injection block.

[POS]
Decision settlement layer in omni-agent cross-examination subsystem.
"""

from __future__ import annotations

from .cross_exam_types import (
    AdoptionChoice,
    AdoptionReceipt,
    AgentRoleTarget,
    CrossExamArbitrationReport,
)


class OneClickArbitrator:
    """Handles 1-Click adoption of an outcome and formats it for permanent workspace context injection."""

    def adopt_verdict(
        self,
        report: CrossExamArbitrationReport,
        choice: AdoptionChoice = AdoptionChoice.SYNTHESIZED_CONSENSUS,
        specific_agent_role: AgentRoleTarget | None = None,
    ) -> AdoptionReceipt:
        """Resolve user choice into an AdoptionReceipt with ready-to-inject working memory markdown block."""
        adopted_agent: AgentRoleTarget | None = None
        adopted_summary: str = ""

        if choice == AdoptionChoice.SYNTHESIZED_CONSENSUS:
            adopted_agent = report.recommended_lead_agent
            adopted_summary = report.synthesized_recommendation
            header = f"# 📌 [Adopted Multi-Agent Consensus: {report.query}]"
            details = [
                f"- **Lead Perspective**: `{report.recommended_lead_agent.value}`",
                f"- **Consensus Summary**: {report.synthesized_recommendation}",
            ]
            if report.consensus.common_ground_facts:
                details.append("- **Agreed Facts**:")
                for fact in report.consensus.common_ground_facts:
                    details.append(f"  * {fact}")
            context_block = f"{header}\n" + "\n".join(details)

        elif choice == AdoptionChoice.LEAD_AGENT:
            target_role = report.recommended_lead_agent
            adopted_agent = target_role
            match = next((o for o in report.agent_outputs if o.agent_role == target_role), None)
            adopted_summary = match.content if match else f"Adopted output from {target_role.value}"
            context_block = (
                f"# 📌 [Adopted Decision: Lead Agent `{target_role.value}`]\n"
                f"**Query**: {report.query}\n\n"
                f"{adopted_summary}"
            )

        else:  # SPECIFIC_AGENT
            target_role = specific_agent_role or report.recommended_lead_agent
            adopted_agent = target_role
            match = next((o for o in report.agent_outputs if o.agent_role == target_role), None)
            adopted_summary = match.content if match else f"Adopted output from {target_role.value}"
            context_block = (
                f"# 📌 [Adopted Decision: Specialist `{target_role.value}`]\n"
                f"**Query**: {report.query}\n\n"
                f"{adopted_summary}"
            )

        return AdoptionReceipt(
            choice=choice,
            adopted_agent=adopted_agent,
            adopted_summary=adopted_summary,
            context_injection_block=context_block.strip(),
        )
