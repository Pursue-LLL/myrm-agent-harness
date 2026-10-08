"""Types and schemas for Model-Native tool pruning and context paging offload suite.

Defines model tiers, tool schemas, blob records for virtual page tables,
stub references, and on-demand page-in slices.

[INPUT]
- None (self-contained; standard library only)

[OUTPUT]
- ModelTier: Target capability tier of the LLM receiving the tool definitions.
- ToolSchemaDefinition: Definition of an agent tool supporting both full and compact presentations.
- ToolBlobRecord: Full raw tool output offloaded into the virtual page table blob store.
- ToolOutputStub: Compact stub card placed into active context in place of massive outputs.
- PageInSlice: Retrieved window slice from an offloaded blob record.
- ToolPagingConfig: Configuration governing tool output offloading and paging thresholds.

[POS]
Types and schemas for Model-Native tool pruning and context paging offload suite.
"""

from dataclasses import dataclass, field
from enum import Enum
import hashlib
import time


class ModelTier(str, Enum):
    """Target capability tier of the LLM receiving the tool definitions."""

    PRO_REASONING = "pro_reasoning"  # e.g., Claude 3.7 / o3 / Gemini Pro: full verbose schema
    STANDARD = "standard"  # e.g., GPT-4o / Claude Sonnet: balanced schema
    FLASH_LITE = "flash_lite"  # e.g., Gemini Flash / Haiku / Mini: stripped compact schema


@dataclass
class ToolSchemaDefinition:
    """Definition of an agent tool supporting both full and compact presentations."""

    name: str
    description: str
    parameters: dict[str, str]  # Param name -> type/constraints
    compact_description: str = ""
    compact_parameters: dict[str, str] = field(default_factory=dict)

    def to_schema_for_tier(self, tier: ModelTier) -> dict[str, str]:
        """Produce format tailored to the given model capability tier."""
        if tier == ModelTier.FLASH_LITE:
            desc = self.compact_description or self.description[:80]
            params = self.compact_parameters or self.parameters
            return {
                "name": self.name,
                "description": desc,
                "parameters_summary": ", ".join(f"{k}:{v}" for k, v in params.items()),
            }
        # Pro and Standard get full definitions
        return {
            "name": self.name,
            "description": self.description,
            "parameters": ", ".join(f"{k}:{v}" for k, v in self.parameters.items()),
        }


@dataclass
class ToolBlobRecord:
    """Full raw tool output offloaded into the virtual page table blob store."""

    blob_id: str
    tool_name: str
    content: str
    byte_size: int
    line_count: int
    summary: str
    created_at: float = field(default_factory=time.time)

    @classmethod
    def create(cls, tool_name: str, raw_content: str, summary: str) -> "ToolBlobRecord":
        """Compute content hash and instantiate offloaded record."""
        digest = hashlib.sha256(raw_content.encode("utf-8")).hexdigest()[:16]
        blob_id = f"blob-{digest}"
        lines = raw_content.splitlines()
        return cls(
            blob_id=blob_id,
            tool_name=tool_name,
            content=raw_content,
            byte_size=len(raw_content.encode("utf-8")),
            line_count=len(lines),
            summary=summary,
        )


@dataclass
class ToolOutputStub:
    """Compact stub card placed into active context in place of massive outputs."""

    blob_id: str
    tool_name: str
    byte_size: int
    line_count: int
    summary: str
    preview_head: str
    ref_uri: str

    def format_card(self) -> str:
        """Format as human/LLM-readable compact stub tag."""
        preview_part = f"\n[Preview]: {self.preview_head}" if self.preview_head else ""
        return (
            f"[Tool Output Offloaded: {self.tool_name} | {self.line_count} lines, {self.byte_size} bytes]\n"
            f"[Summary]: {self.summary}\n"
            f"[Ref]: {self.ref_uri} (Use page_in to read specific lines){preview_part}"
        )


@dataclass
class PageInSlice:
    """Retrieved window slice from an offloaded blob record."""

    blob_id: str
    start_line: int
    end_line: int
    total_lines: int
    content_slice: str
    lines_returned: int


@dataclass
class ToolPagingConfig:
    """Configuration governing tool output offloading and paging thresholds."""

    offload_byte_threshold: int = 1536  # ~1.5KB trigger offloading
    preview_line_count: int = 4
    max_page_lines: int = 100
