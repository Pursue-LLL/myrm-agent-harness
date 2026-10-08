"""Types and models for system prompt strong append channel suite."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


class PromptChannelKind(str, Enum):
    """Channel tier for system prompt components."""

    BASE_CORE_SYSTEM = "base_core_system"
    STRONG_APPEND_SYSTEM = "strong_append_system"
    FULL_REPLACE_SYSTEM = "full_replace_system"
    WORKSPACE_RULE_TIER = "workspace_rule_tier"


@dataclass(frozen=True)
class AppendPromptSource:
    """Represents a discovered system prompt append directive file."""

    source_path: str
    channel_kind: PromptChannelKind
    content: str
    digest: str
    priority: int = 100


@dataclass(frozen=True)
class SystemPromptAssemblyReceipt:
    """Auditable receipt verifying non-diluted system prompt assembly."""

    base_prompt_digest: str
    appended_content_digest: str
    final_system_prompt: str
    is_replaced: bool
    injected_channels: List[PromptChannelKind] = field(default_factory=list)
    anti_drift_verified: bool = True
    active_sources: List[AppendPromptSource] = field(default_factory=list)
    assembly_hash: str = ""
