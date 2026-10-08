"""Types for single-tier workspace rule override interceptor.

[INPUT]
- None (self-contained; standard library only)

[OUTPUT]
- RuleLayerKind: Hierarchy tier of a resolved workspace rule.
- OverrideResolutionKind: Resolution verdict for a directory's rule selection.
- WorkspaceRuleFileEntry: Represents a discovered workspace rule file.
- SingleTierRuleAssemblyReceipt: Cryptographic and auditable receipt of the assembled rule hierarchy.

[POS]
Types for single-tier workspace rule override interceptor.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


class RuleLayerKind(str, Enum):
    """Hierarchy tier of a resolved workspace rule."""

    GLOBAL_ROOT = "global_root"
    PARENT_DIR = "parent_dir"
    CURRENT_DIR_OVERRIDE = "current_dir_override"
    CURRENT_DIR_DEFAULT = "current_dir_default"
    NESTED_CHILD = "nested_child"


class OverrideResolutionKind(str, Enum):
    """Resolution verdict for a directory's rule selection."""

    FALLTHROUGH_STANDARD = "fallthrough_standard"
    SINGLE_TIER_OVERRIDDEN = "single_tier_overridden"
    OPT_OUT_DISABLED = "opt_out_disabled"


@dataclass(frozen=True)
class WorkspaceRuleFileEntry:
    """Represents a discovered workspace rule file."""

    file_path: str
    dir_path: str
    file_name: str
    is_override: bool
    content: str
    content_digest: str


@dataclass(frozen=True)
class SingleTierRuleAssemblyReceipt:
    """Cryptographic and auditable receipt of the assembled rule hierarchy."""

    target_dir: str
    workspace_root: str
    resolution: OverrideResolutionKind
    effective_rule_chain: List[WorkspaceRuleFileEntry] = field(default_factory=list)
    suppressed_default_files: List[str] = field(default_factory=list)
    combined_prompt_content: str = ""
    assembly_hash: str = ""
