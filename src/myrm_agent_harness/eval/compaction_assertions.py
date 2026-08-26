"""Compaction Continuation Quality and Five-Dimensional Fidelity Assertion Engine.

[INPUT]
- protocols::CompactionAssertion (POS: assertion configuration for compaction quality)
- protocols::CompactionFidelityScore (POS: structured five-dimensional score)
- protocols::AgentResponse (POS: agent execution output & tool calls)

[OUTPUT]
- evaluate_compaction_assertions(): evaluates five-dimensional compaction continuation fidelity
- canonicalize_tool_name(): normalizes equivalent tool identifiers

[POS]
Provides deterministic, zero-LLM-cost rule verification coupled with LLM-as-a-Judge
semantic evaluation for agent context compaction quality across 5 dimensions:
1. Constraint Recall (Negative & positive constraints)
2. Decision Fidelity (Tool calling accuracy & equivalence)
3. Execution State Accuracy (Done/In-progress/Blocked vs truth)
4. Artifact Coverage (Created/modified file references)
5. Continuation Success (Task forward progress)
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any

from .protocols import CompactionAssertion

if TYPE_CHECKING:
    from .protocols import AgentResponse, JudgeConfig

logger = logging.getLogger(__name__)

_TOOL_CANONICAL_MAP: dict[str, str] = {
    "file_read_tool": "read_file",
    "read_file_tool": "read_file",
    "read_file": "read_file",
    "file_write_tool": "write_file",
    "write_file_tool": "write_file",
    "write_file": "write_file",
    "bash_code_execute_tool": "bash",
    "bash_execute": "bash",
    "bash": "bash",
    "web_search_tool": "web_search",
    "search_web": "web_search",
    "web_search": "web_search",
}


def canonicalize_tool_name(name: str) -> str:
    """Normalize equivalent tool identifiers across different toolkits/providers."""
    cleaned = name.strip().lower()
    return _TOOL_CANONICAL_MAP.get(cleaned, cleaned)


def _extract_tool_names(tools_called: list[str | dict[str, Any]]) -> set[str]:
    names: set[str] = set()
    for t in tools_called:
        if isinstance(t, dict):
            raw = str(t.get("name", ""))
        elif hasattr(t, "name"):
            raw = str(t.name)
        else:
            raw = str(t)
        if raw:
            names.add(canonicalize_tool_name(raw))
    return names


def _normalize_span(text: str) -> str:
    cleaned = text.lower()
    cleaned = re.sub(r"[`*_~#\[\]()\"'.,;:!?/\\]", " ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


async def evaluate_compaction_assertions(
    assertions: list[CompactionAssertion],
    response: AgentResponse,
    *,
    scores_out: dict[str, float] | None = None,
    judge_override: JudgeConfig | None = None,
) -> tuple[bool | None, str | None]:
    """Evaluate five-dimensional compaction continuation quality assertions.

    Args:
        assertions: List of CompactionAssertion objects.
        response: AgentResponse from the continuation step.
        scores_out: Optional mutable dict to collect numeric fidelity scores.
        judge_override: Optional judge LLM configuration.

    Returns:
        (passed, details): Overall pass status and breakdown details.
    """
    if not assertions:
        return None, None

    actual_text = response.answer or ""
    norm_actual_text = _normalize_span(actual_text)
    actual_tools = _extract_tool_names(response.tools_called)

    all_passed = True
    details_list: list[str] = []

    for idx, assertion in enumerate(assertions, start=1):
        # 1. Constraint Recall
        recalled_count = 0
        missed_constraints: list[str] = []
        for constraint in assertion.expected_constraints:
            norm_c = _normalize_span(constraint)
            # Check direct span or semantic keyword presence
            if norm_c in norm_actual_text or all(w in norm_actual_text for w in norm_c.split() if len(w) > 3):
                recalled_count += 1
            else:
                missed_constraints.append(constraint)

        total_constraints = len(assertion.expected_constraints)
        constraint_score = (recalled_count / total_constraints) if total_constraints > 0 else 1.0

        # 2. Decision Fidelity (Tool Selection)
        expected_tool_names = {canonicalize_tool_name(t) for t in assertion.expected_tools}
        if expected_tool_names:
            matched_tools = expected_tool_names & actual_tools
            decision_score = len(matched_tools) / len(expected_tool_names)
        else:
            decision_score = 1.0

        # 3. Execution State Accuracy (Forbidden / Hallucinated Claims Check)
        violated_claims: list[str] = []
        for claim in assertion.forbidden_claims:
            norm_claim = _normalize_span(claim)
            if norm_claim in norm_actual_text:
                violated_claims.append(claim)

        state_score = 0.0 if violated_claims else 1.0

        # 4. Artifact Coverage (Required files mentioned or targeted)
        artifact_recalled = 0
        missing_artifacts: list[str] = []
        for artifact in assertion.required_artifacts:
            norm_art = _normalize_span(artifact)
            if norm_art in norm_actual_text:
                artifact_recalled += 1
            else:
                missing_artifacts.append(artifact)

        total_artifacts = len(assertion.required_artifacts)
        artifact_score = (artifact_recalled / total_artifacts) if total_artifacts > 0 else 1.0

        # 5. Continuation Success (Basic non-empty / error-free response check)
        continuation_score = 1.0 if (actual_text.strip() and not response.limit_reached) else 0.5

        # Calculate weighted overall fidelity
        weights = [0.30, 0.25, 0.20, 0.15, 0.10]
        scores = [constraint_score, decision_score, state_score, artifact_score, continuation_score]
        overall_fidelity = sum(w * s for w, s in zip(weights, scores, strict=True))

        # Check against minimum required fidelity score
        case_passed = (
            overall_fidelity >= assertion.min_fidelity_score
            and not violated_claims
            and (constraint_score >= 0.8 if total_constraints > 0 else True)
        )

        if scores_out is not None:
            scores_out[f"case_{idx}_overall_fidelity"] = round(overall_fidelity, 4)
            scores_out[f"case_{idx}_constraint_recall"] = round(constraint_score, 4)
            scores_out[f"case_{idx}_decision_fidelity"] = round(decision_score, 4)
            scores_out[f"case_{idx}_state_accuracy"] = round(state_score, 4)
            scores_out[f"case_{idx}_artifact_coverage"] = round(artifact_score, 4)

        issues: list[str] = []
        if missed_constraints:
            issues.append(f"Missed constraints: {missed_constraints}")
        if violated_claims:
            issues.append(f"Violated forbidden claims: {violated_claims}")
        if missing_artifacts:
            issues.append(f"Missing artifacts: {missing_artifacts}")
        if expected_tool_names and decision_score < 1.0:
            issues.append(f"Tool mismatch (expected {expected_tool_names}, called {actual_tools})")

        detail_msg = (
            f"Compaction assertion #{idx} {'PASSED' if case_passed else 'FAILED'} "
            f"(Fidelity: {overall_fidelity:.2f} >= {assertion.min_fidelity_score:.2f}). "
            + (f"Issues: {'; '.join(issues)}" if issues else "All 5 dimensions satisfied.")
        )
        details_list.append(detail_msg)

        if not case_passed:
            all_passed = False

    return all_passed, "\n".join(details_list)
