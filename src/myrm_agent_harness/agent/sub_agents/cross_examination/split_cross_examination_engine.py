# [INPUT]: AgentExecutionOutput, AgentRoleTarget, ConsensusDeltaHighlighter, CrossExamArbitrationReport, Sequence
# [OUTPUT]: SplitCrossExaminationEngine
# [POS]: agent/sub_agents/cross_examination/split_cross_examination_engine.py

"""Engine orchestrating concurrent multi-agent dispatch and cross-examination report generation.

[INPUT]
- AgentExecutionOutput, AgentRoleTarget, ConsensusDeltaHighlighter, CrossExamArbitrationReport: Subsystem models.

[OUTPUT]
- SplitCrossExaminationEngine: Dispatches queries across candidate agents and synthesizes outcomes.

[POS]
Execution coordination layer in omni-agent cross-examination subsystem.
"""

from __future__ import annotations

import time
from typing import Callable, Mapping, Sequence

from .consensus_delta_highlighter import ConsensusDeltaHighlighter
from .cross_exam_types import (
    AgentExecutionOutput,
    AgentRoleTarget,
    CrossExamArbitrationReport,
)


class SplitCrossExaminationEngine:
    """Coordinates execution across 2 to 3 candidate agents and produces a structured arbitration report."""

    def __init__(self, highlighter: ConsensusDeltaHighlighter | None = None) -> None:
        self._highlighter = highlighter or ConsensusDeltaHighlighter()

    def generate_simulated_role_output(
        self,
        query: str,
        role: AgentRoleTarget,
    ) -> AgentExecutionOutput:
        """Heuristic baseline generator for standard role perspective when mock or standalone execution is needed."""
        start_t = time.perf_counter()

        if role == AgentRoleTarget.SECURITY_CRITIC:
            display_name = "🛡️ Security Sentinel"
            content = (
                f"Security Review for: '{query}'. "
                "CRITICAL: Restrict file permissions and verify lack of unauthenticated command injection. "
                "Require explicit human confirmation for irreversible modifications. "
                "Deploy with minimal least-privilege IAM credentials."
            )
        elif role == AgentRoleTarget.ARCHITECT_PLANNER:
            display_name = "🏛️ Architect Planner"
            content = (
                f"Architectural Evaluation for: '{query}'. "
                "Decouple state storage from computing instances to preserve horizontal scalability. "
                "Ensure strict backward-compatible API contracts across subsystem seams. "
                "Balance implementation velocity with long-term technical debt."
            )
        elif role == AgentRoleTarget.CODING_SPECIALIST:
            display_name = "💻 Coding Specialist"
            content = (
                f"Code Implementation for: '{query}'. "
                "Strict typing with zero Any annotations. "
                "Decompose files to under 400 lines and enforce comprehensive unit test coverage. "
                "Optimize critical paths with caching and benchmark verification."
            )
        elif role == AgentRoleTarget.DEEP_RESEARCH:
            display_name = "📚 Research Specialist"
            content = (
                f"Literature & SOTA Survey for: '{query}'. "
                "Examine industry benchmarks and existing open-source precedent architectures. "
                "Extract common patterns and avoid proprietary vendor lock-in. "
                "Validate empirical throughput numbers against production case studies."
            )
        else:  # LOCAL_FAST
            display_name = "⚡ Local Fast Agent"
            content = (
                f"Fast execution on: '{query}'. "
                "Quick zero-overhead command response with minimal tokens and immediate output."
            )

        latency = (time.perf_counter() - start_t) * 1000.0 + 12.0
        claims = self._highlighter.extract_key_claims(content)

        return AgentExecutionOutput(
            agent_role=role,
            display_name=display_name,
            content=content,
            latency_ms=latency,
            key_claims=claims,
        )

    def conduct_cross_examination(
        self,
        query: str,
        target_roles: Sequence[AgentRoleTarget],
        custom_executors: Mapping[AgentRoleTarget, Callable[[str], str]] | None = None,
    ) -> CrossExamArbitrationReport:
        """Run cross-examination across selected roles, either using custom handlers or default perspectives."""
        outputs: list[AgentExecutionOutput] = []

        for role in target_roles:
            if custom_executors and role in custom_executors:
                t0 = time.perf_counter()
                try:
                    res_text = custom_executors[role](query)
                except Exception as exc:  # pylint: disable=broad-exception-caught
                    res_text = f"Error during agent execution: {exc}"
                lat = (time.perf_counter() - t0) * 1000.0
                claims = self._highlighter.extract_key_claims(res_text)
                outputs.append(
                    AgentExecutionOutput(
                        agent_role=role,
                        display_name=f"Custom {role.value}",
                        content=res_text,
                        latency_ms=lat,
                        key_claims=claims,
                    )
                )
            else:
                outputs.append(self.generate_simulated_role_output(query, role))

        consensus = self._highlighter.compute_consensus(outputs)
        divergences = self._highlighter.detect_divergences(outputs)

        # Decide recommended lead agent
        if any(o.agent_role == AgentRoleTarget.SECURITY_CRITIC for o in outputs) and any(
            d.risk_level in ("high_risk", "warning") for d in divergences
        ):
            recommended_lead = AgentRoleTarget.SECURITY_CRITIC
        elif any(o.agent_role == AgentRoleTarget.ARCHITECT_PLANNER for o in outputs):
            recommended_lead = AgentRoleTarget.ARCHITECT_PLANNER
        elif outputs:
            recommended_lead = outputs[0].agent_role
        else:
            recommended_lead = AgentRoleTarget.LOCAL_FAST

        # Synthesize integrated recommendation
        rec_parts: list[str] = [
            f"Harmonized recommendation guided by `{recommended_lead.value}`.",
        ]
        if consensus.common_ground_facts:
            rec_parts.append(f"Accepted baseline: {'; '.join(consensus.common_ground_facts[:2])}.")
        if divergences:
            rec_parts.append(
                f"Resolved trade-off: prioritize safety guardrails before maximum implementation throughput."
            )

        synthesized = " ".join(rec_parts)

        return CrossExamArbitrationReport(
            query=query,
            agent_outputs=tuple(outputs),
            consensus=consensus,
            divergences=divergences,
            synthesized_recommendation=synthesized,
            recommended_lead_agent=recommended_lead,
        )
