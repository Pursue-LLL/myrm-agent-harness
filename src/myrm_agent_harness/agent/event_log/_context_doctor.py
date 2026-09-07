"""Context Doctor: Token breakdown and hotspot analyzer for execution traces.

Analyzes an ExecutionTrace to compute token distributions across 4 key dimensions:
- System & Rules prompt overhead
- Conversation turns (user & assistant messages)
- Tool call input/output payloads
- File content loads

Identifies the top token-consuming tool calls (hotspots) to empower developers
and end-users with crystal-clear context visibility without manual cache destruction.

[INPUT]
- event_log.trace_types::ExecutionTrace, ToolCallRecord (POS: trace types)
- utils.token_estimation::estimate_content_tokens (POS: token estimation)

[OUTPUT]
- ContextBreakdown: dataclass for context breakdown and hotspot analytics
- ContextHotspot: dataclass for top token hotspot details
- analyze_context_breakdown: pure function analyzing an ExecutionTrace

[POS]
Stateless pure function context breakdown analyzer in event log domain. Computes 4-color token
breakdown (system, chat, tool, file) and identifies tool hotspots without mutating traces.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Sequence

from myrm_agent_harness.utils.token_estimation import estimate_content_tokens

if TYPE_CHECKING:
    from .trace_types import ExecutionTrace, ToolCallRecord


@dataclass(frozen=True, slots=True)
class ContextHotspot:
    """Represents a significant token hotspot in tool executions."""

    tool_name: str
    tokens: int
    step_sequence: int
    status: str  # "auto_pruned", "active", "error"
    summary: str | None = None


@dataclass(frozen=True, slots=True)
class ContextBreakdown:
    """Four-color token breakdown and health diagnosis for a session."""

    system_tokens: int = 0
    chat_tokens: int = 0
    tool_tokens: int = 0
    file_tokens: int = 0
    total_context_tokens: int = 0
    health_score: int = 100  # 0 to 100
    diagnosis_status: str = "healthy"  # "healthy", "warning", "critical"
    diagnosis_message: str = "Context is healthy and well-balanced."
    hotspots: list[ContextHotspot] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "system_tokens": self.system_tokens,
            "chat_tokens": self.chat_tokens,
            "tool_tokens": self.tool_tokens,
            "file_tokens": self.file_tokens,
            "total_context_tokens": self.total_context_tokens,
            "health_score": self.health_score,
            "diagnosis_status": self.diagnosis_status,
            "diagnosis_message": self.diagnosis_message,
            "hotspots": [
                {
                    "tool_name": h.tool_name,
                    "tokens": h.tokens,
                    "step_sequence": h.step_sequence,
                    "status": h.status,
                    "summary": h.summary,
                }
                for h in self.hotspots
            ],
        }


_FILE_TOOL_NAMES = frozenset(
    {
        "file_read_tool",
        "file_write_tool",
        "read_file",
        "write_file",
        "edit_file",
        "apply_file_diff",
        "list_dir",
        "glob_tool",
        "grep_tool",
    }
)


def _estimate_payload_tokens(data: object) -> int:
    """Estimate token count of raw structured input/output data."""
    if data is None:
        return 0
    if isinstance(data, str):
        return estimate_content_tokens(data)
    try:
        serialized = json.dumps(data, ensure_ascii=False)
        return estimate_content_tokens(serialized)
    except Exception:
        return 0


def analyze_context_breakdown(trace: ExecutionTrace) -> ContextBreakdown:
    """Analyze token breakdown and detect hotspots for an ExecutionTrace."""
    file_tokens = 0
    other_tool_tokens = 0
    hotspot_candidates: list[ContextHotspot] = []

    for tc in trace.tool_calls:
        in_tok = _estimate_payload_tokens(tc.input_data)
        out_tok = _estimate_payload_tokens(tc.output_data)
        if out_tok == 0 and tc.output_summary:
            out_tok = estimate_content_tokens(tc.output_summary)

        call_total_tok = in_tok + out_tok

        # Status determination
        if not tc.success:
            status = "error"
        elif "COMPACTED:" in str(tc.output_summary or "") or "[Tool output pruned:" in str(tc.output_summary or ""):
            status = "auto_pruned"
        else:
            status = "active"

        if tc.tool_name in _FILE_TOOL_NAMES:
            file_tokens += call_total_tok
        else:
            other_tool_tokens += call_total_tok

        if call_total_tok >= 1500 or not tc.success:
            hotspot_candidates.append(
                ContextHotspot(
                    tool_name=tc.tool_name,
                    tokens=call_total_tok,
                    step_sequence=tc.sequence,
                    status=status,
                    summary=tc.output_summary[:120] if tc.output_summary else None,
                )
            )

    # Sort hotspots by tokens descending and pick top 3
    hotspot_candidates.sort(key=lambda h: h.tokens, reverse=True)
    top_hotspots = hotspot_candidates[:3]

    # Calculate aggregate chat and prompt tokens
    prompt_tokens = sum(lc.prompt_tokens for lc in trace.llm_calls)
    completion_tokens = sum(lc.completion_tokens for lc in trace.llm_calls)
    total_tokens = trace.total_tokens or (prompt_tokens + completion_tokens)

    # If we have prompt tokens, derive system vs chat tokens
    all_tool_tokens = file_tokens + other_tool_tokens
    if prompt_tokens > all_tool_tokens:
        remaining_prompt = prompt_tokens - all_tool_tokens
        # Estimate ~60% system rules & templates, ~40% conversation history
        system_tokens = max(int(remaining_prompt * 0.6), 500)
        chat_tokens = max(remaining_prompt - system_tokens, 200)
    else:
        system_tokens = max(int(total_tokens * 0.15), 500)
        chat_tokens = max(int(total_tokens * 0.10), 200)

    total_context = system_tokens + chat_tokens + other_tool_tokens + file_tokens

    # Compute health score and diagnosis
    health_score = 100
    diagnosis_status = "healthy"
    diagnosis_message = "Context distribution is well-balanced."

    if total_context > 64000:
        health_score -= 25
        diagnosis_status = "warning"
        diagnosis_message = "High total context consumption. Approaching model saturation ceiling."
    elif total_context > 32000:
        health_score -= 10

    if other_tool_tokens > total_context * 0.70 and other_tool_tokens > 10000:
        health_score -= 20
        diagnosis_status = "warning"
        diagnosis_message = "Tool outputs dominate over 70% of context. Pruning engine active."

    active_heavy_hotspots = [h for h in top_hotspots if h.status == "active" and h.tokens > 8000]
    if active_heavy_hotspots:
        health_score -= 20
        diagnosis_status = "warning"
        diagnosis_message = f"Found {len(active_heavy_hotspots)} large active tool payload(s) consuming >8k tokens."

    # Clamp health score
    health_score = max(min(health_score, 100), 20)
    if health_score < 60:
        diagnosis_status = "critical"

    return ContextBreakdown(
        system_tokens=system_tokens,
        chat_tokens=chat_tokens,
        tool_tokens=other_tool_tokens,
        file_tokens=file_tokens,
        total_context_tokens=total_context,
        health_score=health_score,
        diagnosis_status=diagnosis_status,
        diagnosis_message=diagnosis_message,
        hotspots=top_hotspots,
    )
