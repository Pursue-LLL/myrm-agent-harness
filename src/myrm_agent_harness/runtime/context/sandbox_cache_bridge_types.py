"""Sandbox state-aware context cache bridge types and data models.

Defines schemas for fine-grained sandbox filesystem change events, static prefix snapshots,
incremental patch bundles, and stitched context assemblies to preserve provider KV prefix cache.

[INPUT]
- None (self-contained; standard library only)

[OUTPUT]
- FileChangeKind: Classification of sandbox filesystem mutation.
- InvalidationScope: Scope of context invalidation necessitated by filesystem changes.
- SandboxFileChangeEvent: Fine-grained record of an individual file mutation captured inside the sandbox.
- StaticPrefixSnapshot: Immutable snapshot of the core prompt prefix kept stable for provider KV caching.
- IncrementalPatchBundle: Compilation of captured sandbox mutations ready for tail-only stitching.
- StitchedContextAssembly: Final context payload prepared for model invocation.

[POS]
Sandbox state-aware context cache bridge types and data models.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum


class FileChangeKind(StrEnum):
    """Classification of sandbox filesystem mutation."""

    CREATED = "created"
    MODIFIED = "modified"
    DELETED = "deleted"
    RENAMED = "renamed"


class InvalidationScope(StrEnum):
    """Scope of context invalidation necessitated by filesystem changes."""

    TAIL_PATCH_ONLY = "tail_patch_only"
    FULL_PREFIX_INVALIDATION = "full_prefix_invalidation"


@dataclass(frozen=True)
class SandboxFileChangeEvent:
    """Fine-grained record of an individual file mutation captured inside the sandbox."""

    file_path: str
    kind: FileChangeKind
    diff_hunk: str | None = None
    is_critical_config: bool = False
    metadata: Mapping[str, str] = field(default_factory=dict)
    timestamp_ms: int = 0


@dataclass(frozen=True)
class StaticPrefixSnapshot:
    """Immutable snapshot of the core prompt prefix kept stable for provider KV caching."""

    prefix_id: str
    system_prompt: str
    frozen_workspace_skeleton: str
    content_hash: str
    created_at_ms: int = 0

    @property
    def full_prefix_text(self) -> str:
        """Render the complete static prefix text."""
        return f"{self.system_prompt}\n\n=== Workspace Baseline ===\n{self.frozen_workspace_skeleton}"


@dataclass(frozen=True)
class IncrementalPatchBundle:
    """Compilation of captured sandbox mutations ready for tail-only stitching."""

    patch_id: str
    base_prefix_hash: str
    events: tuple[SandboxFileChangeEvent, ...]
    invalidation_scope: InvalidationScope
    formatted_tail_diff: str
    events_count: int = 0
    created_at_ms: int = 0


@dataclass(frozen=True)
class StitchedContextAssembly:
    """Final context payload prepared for model invocation."""

    prefix_snapshot: StaticPrefixSnapshot
    conversation_body: str
    tail_patch: IncrementalPatchBundle
    full_prompt_text: str
    cache_hit_ratio_projected: float
