"""Heavy MCP Payload Fetch Summarizer & Contamination Doctor (Item 44).

[INPUT]
- Raw bulky payloads from external tools, extraction target specs,
  isolation flags, and artifact directories.

[OUTPUT]
- Structured McpPayloadSummaryArtifact reducing context token usage,
  and ContaminationReport diagnosing direct payload contamination.

[POS]
- Harness sub_agents layer guard shielding parent context from bulky MCP dumps.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime

from .types import (
    ContaminationReport,
    ContaminationRiskLevel,
    McpPayloadSummaryArtifact,
    PayloadExtractionTarget,
)

logger = logging.getLogger(__name__)

# Byte thresholds for payload contamination gating
SAFE_PAYLOAD_MAX_BYTES = 4096
SEVERE_PAYLOAD_THRESHOLD_BYTES = 16384


class McpSummarizerError(ValueError):
    """Raised when summarizer encounters invalid configuration or malformed payloads."""


class HeavyMcpPayloadSummarizer:
    """Extracts compact structured summaries from heavy MCP responses to protect parent context."""

    def __init__(self, default_target: PayloadExtractionTarget | None = None) -> None:
        self._default_target = default_target or PayloadExtractionTarget()

    def is_heavy_payload(self, raw_payload: str, threshold_bytes: int = SAFE_PAYLOAD_MAX_BYTES) -> bool:
        """Determine whether raw string exceeds safe inline context threshold."""
        return len(raw_payload.encode("utf-8")) > threshold_bytes

    def summarize_payload(
        self,
        source_tool: str,
        raw_payload: str,
        target: PayloadExtractionTarget | None = None,
        artifact_store_path: str | None = None,
    ) -> McpPayloadSummaryArtifact:
        """Parse bulky raw payload, extract structured keys, and compute token compression ratio."""
        if not source_tool.strip():
            msg = "Source tool or MCP name cannot be empty."
            raise McpSummarizerError(msg)

        active_target = target or self._default_target
        raw_bytes = len(raw_payload.encode("utf-8"))
        extracted_fields: dict[str, str] = {}
        summary_lines: list[str] = []

        # Attempt JSON parsing for structured extraction
        try:
            parsed = json.loads(raw_payload)
            if isinstance(parsed, dict):
                for k, v in parsed.items():
                    if not active_target.required_keys or k in active_target.required_keys:
                        if isinstance(v, list):
                            truncated_list = v[: active_target.summarize_nested_lists_limit]
                            extracted_fields[k] = f"List({len(v)} items): {json.dumps(truncated_list, ensure_ascii=False)}"
                        elif isinstance(v, dict):
                            extracted_fields[k] = f"Dict({len(v)} keys)"
                        else:
                            val_str = str(v)
                            extracted_fields[k] = val_str[:200]
                summary_lines.append(f"### MCP Response Summary from `{source_tool}`")
                summary_lines.append(f"- **Total Root Keys**: {len(parsed)}")
                for field_name, preview in extracted_fields.items():
                    summary_lines.append(f"- **{field_name}**: {preview}")
            elif isinstance(parsed, list):
                extracted_fields["item_count"] = str(len(parsed))
                preview_items = parsed[: active_target.summarize_nested_lists_limit]
                summary_lines.append(f"### Array Payload Summary from `{source_tool}`")
                summary_lines.append(f"- Total Items: {len(parsed)}")
                summary_lines.append(f"- Sample Preview: {json.dumps(preview_items, ensure_ascii=False)[:300]}")
            else:
                summary_lines.append(f"### Scalar Payload: {str(parsed)[:300]}")
        except json.JSONDecodeError:
            # Fallback for plain text or markdown tables
            summary_lines.append(f"### Raw Text Extract from `{source_tool}`")
            first_chunk = raw_payload.strip()[:600]
            summary_lines.append(first_chunk)
            extracted_fields["text_length"] = str(len(raw_payload))

        summary_text = "\n".join(summary_lines)
        summary_bytes = len(summary_text.encode("utf-8"))

        saving_ratio = 0.0
        if raw_bytes > 0:
            saving_ratio = max(0.0, float(raw_bytes - summary_bytes) / float(raw_bytes))

        artifact_id = f"mcp-summary-{uuid.uuid4().hex[:8]}"

        logger.info(
            "Summarized payload for '%s': raw=%d bytes -> summary=%d bytes (saving=%.1f%%)",
            source_tool,
            raw_bytes,
            summary_bytes,
            saving_ratio * 100.0,
        )

        return McpPayloadSummaryArtifact(
            artifact_id=artifact_id,
            source_tool_or_mcp=source_tool,
            raw_payload_bytes=raw_bytes,
            summary_bytes=summary_bytes,
            token_saving_ratio=saving_ratio,
            summary_text=summary_text,
            extracted_fields=extracted_fields,
            file_reference_path=artifact_store_path,
            created_at=datetime.now(tz=UTC),
        )


class McpContaminationDoctor:
    """Diagnostics engine inspecting MCP tool usage and flagging unisolated context pollution."""

    def diagnose_payload(
        self,
        raw_payload: str,
        is_isolated_via_subagent: bool,
    ) -> ContaminationReport:
        """Audit payload size and report contamination severity when directly dumped into main chat."""
        raw_bytes = len(raw_payload.encode("utf-8"))
        estimated_tokens = max(1, raw_bytes // 4)

        if is_isolated_via_subagent:
            return ContaminationReport(
                risk_level=ContaminationRiskLevel.SAFE,
                payload_bytes=raw_bytes,
                estimated_tokens=estimated_tokens,
                is_isolated_via_subagent=True,
                remediation_advice="Payload properly isolated inside dedicated subagent worker.",
            )

        if raw_bytes <= SAFE_PAYLOAD_MAX_BYTES:
            return ContaminationReport(
                risk_level=ContaminationRiskLevel.SAFE,
                payload_bytes=raw_bytes,
                estimated_tokens=estimated_tokens,
                is_isolated_via_subagent=False,
                remediation_advice="Payload within safe inline context limit.",
            )

        if raw_bytes <= SEVERE_PAYLOAD_THRESHOLD_BYTES:
            return ContaminationReport(
                risk_level=ContaminationRiskLevel.SUSPICIOUS,
                payload_bytes=raw_bytes,
                estimated_tokens=estimated_tokens,
                is_isolated_via_subagent=False,
                remediation_advice=(
                    f"Warning: {raw_bytes}B payload (~{estimated_tokens} tokens) directly injected into parent. "
                    "Recommend delegating fetch to prebuilt 'mcp-data-summarizer' subagent."
                ),
            )

        return ContaminationReport(
            risk_level=ContaminationRiskLevel.SEVERE_CONTAMINATION,
            payload_bytes=raw_bytes,
            estimated_tokens=estimated_tokens,
            is_isolated_via_subagent=False,
            remediation_advice=(
                f"Severe Contamination Risk: {raw_bytes}B bulky payload directly threatens main context window! "
                "Immediate remediation: enforce 'mcp-data-summarizer' delegation to extract structured summary artifact."
            ),
        )
