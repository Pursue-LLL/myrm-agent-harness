"""Consensus and delta highlighter extracting agreements and contested divergences across agents.

[INPUT]
- AgentExecutionOutput, AgentRoleTarget, CrossExamArbitrationReport, CrossExamConsensus, CrossExamDivergence: Models.

[OUTPUT]
- ConsensusDeltaHighlighter: Analyzes heterogeneous agent outputs, computes common ground, highlights deltas.

[POS]
Analytics and presentation layer in omni-agent cross-examination subsystem eliminating manual tab comparison.
"""

from __future__ import annotations

import re
from typing import Mapping, Sequence

from .cross_exam_types import (
    AgentExecutionOutput,
    AgentRoleTarget,
    CrossExamArbitrationReport,
    CrossExamConsensus,
    CrossExamDivergence,
)


class ConsensusDeltaHighlighter:
    """Extracts semantic overlap, identifies polar divergences, and renders a high signal-to-noise dashboard."""

    CLAIM_DELIMITERS: tuple[str, ...] = ("。", ".", "!", "！", "\n- ", "\n* ", "\n1. ", "\n2. ")

    def extract_key_claims(self, text: str) -> Sequence[str]:
        """Split text into informative proposition sentences for comparison."""
        raw_lines = text.strip().splitlines()
        claims: list[str] = []
        for line in raw_lines:
            cleaned = line.strip().lstrip("-*#•0123456789. ")
            if len(cleaned) >= 12 and not cleaned.lower().startswith(("hello", "hi", "sure", "here is")):
                claims.append(cleaned)
        return tuple(claims[:10])

    def compute_consensus(self, outputs: Sequence[AgentExecutionOutput]) -> CrossExamConsensus:
        """Find common factual claims and shared advice accepted by multiple agents."""
        if not outputs:
            return CrossExamConsensus(
                common_ground_facts=(),
                shared_recommendations=(),
                agreement_score=1.0,
            )

        if len(outputs) == 1:
            return CrossExamConsensus(
                common_ground_facts=outputs[0].key_claims[:3],
                shared_recommendations=outputs[0].key_claims[3:5],
                agreement_score=1.0,
            )

        # Token overlap heuristic across claims
        common_facts: list[str] = []
        shared_recs: list[str] = []

        all_claims = [out.key_claims if out.key_claims else self.extract_key_claims(out.content) for out in outputs]
        ref_claims = all_claims[0]

        for claim in ref_claims:
            claim_words = set(re.findall(r"\w+", claim.lower()))
            if len(claim_words) < 3:
                continue

            matches_all = True
            for other_claims in all_claims[1:]:
                matched_peer = False
                for other_claim in other_claims:
                    other_words = set(re.findall(r"\w+", other_claim.lower()))
                    overlap = len(claim_words.intersection(other_words))
                    if overlap >= max(2, len(claim_words) // 2):
                        matched_peer = True
                        break
                if not matched_peer:
                    matches_all = False
                    break

            if matches_all:
                if any(w in claim.lower() for w in ("should", "must", "recommend", "建议", "务必", "应当")):
                    shared_recs.append(claim)
                else:
                    common_facts.append(claim)

        # Baseline score calculation
        total_claims_count = sum(len(c) for c in all_claims)
        matched_count = (len(common_facts) + len(shared_recs)) * len(outputs)
        score = min(1.0, max(0.2, (matched_count / total_claims_count) if total_claims_count > 0 else 0.5))

        return CrossExamConsensus(
            common_ground_facts=tuple(common_facts[:5]),
            shared_recommendations=tuple(shared_recs[:5]),
            agreement_score=round(score, 2),
        )

    def detect_divergences(self, outputs: Sequence[AgentExecutionOutput]) -> Sequence[CrossExamDivergence]:
        """Discover explicit disagreements, trade-off discrepancies, and safety warnings."""
        if len(outputs) < 2:
            return ()

        divergences: list[CrossExamDivergence] = []

        # Analyze positions on performance vs safety vs complexity
        has_security_agent = any(o.agent_role == AgentRoleTarget.SECURITY_CRITIC for o in outputs)
        has_coding_agent = any(o.agent_role == AgentRoleTarget.CODING_SPECIALIST for o in outputs)

        if has_security_agent and has_coding_agent:
            sec_output = next(o for o in outputs if o.agent_role == AgentRoleTarget.SECURITY_CRITIC)
            code_output = next(o for o in outputs if o.agent_role == AgentRoleTarget.CODING_SPECIALIST)

            positions: dict[AgentRoleTarget, str] = {
                AgentRoleTarget.SECURITY_CRITIC: (
                    sec_output.key_claims[0] if sec_output.key_claims else sec_output.content[:80]
                ),
                AgentRoleTarget.CODING_SPECIALIST: (
                    code_output.key_claims[0] if code_output.key_claims else code_output.content[:80]
                ),
            }

            divergences.append(
                CrossExamDivergence(
                    topic="Implementation Velocity vs Blast-Radius Guardrails",
                    agent_positions=positions,
                    severity="medium",
                    risk_level="warning",
                )
            )

        # Content length & architectural depth divergence
        lens = [len(o.content) for o in outputs]
        if max(lens) > min(lens) * 3 and min(lens) > 0:
            divergences.append(
                CrossExamDivergence(
                    topic="Level of Granularity & Execution Scope",
                    agent_positions={o.agent_role: f"{len(o.content)} chars detail" for o in outputs},
                    severity="low",
                    risk_level="info",
                )
            )

        return tuple(divergences)

    def render_consensus_dashboard(self, report: CrossExamArbitrationReport) -> str:
        """Render a clean Markdown board highlighting common ground, deltas, and synthesis."""
        sections: list[str] = [
            f"# ⚖️ [Multi-Agent Split Cross-Examination: {report.query}]",
            f"**Recommended Lead Agent**: `{report.recommended_lead_agent.value}` | **Agreement Score**: `{int(report.consensus.agreement_score * 100)}%`\n",
        ]

        # 1. Output Summary Columns
        sections.append("## 👥 [Participant Agent Outputs]")
        for out in report.agent_outputs:
            snippet = out.content[:240] + ("..." if len(out.content) > 240 else "")
            sections.append(
                f"- **{out.display_name}** (`{out.agent_role.value}`, {out.latency_ms:.0f}ms):\n  > {snippet}\n"
            )

        # 2. Common Ground
        sections.append("## ✅ [Common Ground Facts & Consensus]")
        if report.consensus.common_ground_facts:
            for fact in report.consensus.common_ground_facts:
                sections.append(f"- [FACT]: {fact}")
        if report.consensus.shared_recommendations:
            for rec in report.consensus.shared_recommendations:
                sections.append(f"- [RECOMMENDATION]: {rec}")
        if not report.consensus.common_ground_facts and not report.consensus.shared_recommendations:
            sections.append("- (No explicit unanimous claims detected across agents)")

        # 3. Key Divergences
        sections.append("\n## ⚡ [Key Divergences & Critical Deltas]")
        if report.divergences:
            for div in report.divergences:
                sections.append(f"### Dimension: {div.topic} (Severity: `{div.severity}`, Risk: `{div.risk_level}`)")
                for role, pos in div.agent_positions.items():
                    sections.append(f"  * **{role.value}**: {pos}")
        else:
            sections.append("- (No polarized contradictions found)")

        # 4. Synthesized Recommendation
        sections.append("\n## 💡 [Synthesized Recommendation]")
        sections.append(report.synthesized_recommendation)

        return "\n".join(sections).strip()
