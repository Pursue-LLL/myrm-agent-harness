"""Domain types and contracts for Heavy MCP Payload Fetch Subagent (Item 44).

[INPUT]
- Raw large payload strings/dicts from external MCP tools, fetch responses,
  extraction rules, and context contamination telemetry.

[OUTPUT]
- Strongly-typed models: ContaminationRiskLevel, ContaminationReport,
  PayloadExtractionTarget, McpPayloadSummaryArtifact, SubagentPresetSpec.

[POS]
- Harness sub_agents layer contracts for heavy payload isolation and summarization.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import UTC, datetime


class ContaminationRiskLevel(enum.StrEnum):
    """Context contamination threat level when injecting MCP payloads directly into main chat."""

    SAFE = "safe"
    SUSPICIOUS = "suspicious"
    SEVERE_CONTAMINATION = "severe_contamination"


@dataclass(frozen=True)
class PayloadExtractionTarget:
    """Extraction rules and field selection for structuring heavy payloads."""

    required_keys: tuple[str, ...] = ()
    max_summary_tokens: int = 800
    strip_raw_binary: bool = True
    preserve_markdown_tables: bool = True
    summarize_nested_lists_limit: int = 5


@dataclass(frozen=True)
class McpPayloadSummaryArtifact:
    """Summary artifact returned to parent agent without polluting context with raw payloads."""

    artifact_id: str
    source_tool_or_mcp: str
    raw_payload_bytes: int
    summary_bytes: int
    token_saving_ratio: float
    summary_text: str
    extracted_fields: dict[str, str] = field(default_factory=dict)
    file_reference_path: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(tz=UTC))


@dataclass(frozen=True)
class ContaminationReport:
    """Diagnostic audit report evaluating payload size and recommending subagent isolation."""

    risk_level: ContaminationRiskLevel
    payload_bytes: int
    estimated_tokens: int
    is_isolated_via_subagent: bool
    remediation_advice: str
    detected_at: datetime = field(default_factory=lambda: datetime.now(tz=UTC))


@dataclass(frozen=True)
class SubagentPresetSpec:
    """Specification of the prebuilt mcp-data-summarizer subagent."""

    name: str = "mcp-data-summarizer"
    description: str = (
        "Dedicated isolated subagent fetching heavy MCP payloads (Figma/Notion/TAPD/large docs) "
        "and returning concise structured summaries to prevent parent context contamination."
    )
    tools_whitelist: tuple[str, ...] = ("read_file", "write_file", "search_web")
    default_extraction_target: PayloadExtractionTarget = field(
        default_factory=PayloadExtractionTarget
    )
