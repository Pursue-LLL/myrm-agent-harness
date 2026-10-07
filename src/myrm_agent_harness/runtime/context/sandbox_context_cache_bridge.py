"""Sandbox state-aware context cache bridge and incremental patch stitching engine.

Prevents provider KV cache thrashing caused by in-sandbox file mutations by anchoring
static core prefixes and stitching file system delta patches strictly at the context tail.
"""

from __future__ import annotations

import hashlib
import time
import uuid

from .sandbox_cache_bridge_types import (
    IncrementalPatchBundle,
    InvalidationScope,
    StaticPrefixSnapshot,
    StitchedContextAssembly,
)
from .sandbox_fs_event_probe import SandboxFsEventProbe


class SandboxContextCacheBridge:
    """Bridges sandbox filesystem state with LLM context assembly to preserve KV caching."""

    def __init__(
        self,
        system_prompt: str = "",
        workspace_skeleton: str = "",
    ) -> None:
        self._prefix_snapshot: StaticPrefixSnapshot = (
            self._build_prefix_snapshot(system_prompt, workspace_skeleton)
        )
        self._total_stitches_count: int = 0
        self._cache_preserved_count: int = 0

    @property
    def current_prefix(self) -> StaticPrefixSnapshot:
        """Return the active static prefix snapshot."""
        return self._prefix_snapshot

    def refresh_prefix(
        self,
        system_prompt: str,
        workspace_skeleton: str,
    ) -> StaticPrefixSnapshot:
        """Force a controlled refresh of the static prefix."""
        self._prefix_snapshot = self._build_prefix_snapshot(
            system_prompt, workspace_skeleton
        )
        return self._prefix_snapshot

    def stitch_context(
        self,
        probe: SandboxFsEventProbe,
        conversation_body: str,
        updated_system_prompt: str | None = None,
        updated_workspace_skeleton: str | None = None,
    ) -> StitchedContextAssembly:
        """Stitch together static prefix, conversation history, and sandbox delta patch.

        Guarantees that ordinary code modifications append strictly at the tail,
        preserving provider prefix caching for the core prompt.
        """
        self._total_stitches_count += 1
        base_hash = self._prefix_snapshot.content_hash
        patch: IncrementalPatchBundle = probe.drain_and_compile_patch(base_hash)

        if patch.invalidation_scope == InvalidationScope.FULL_PREFIX_INVALIDATION:
            # Controlled prefix invalidation due to critical config/schema change
            sys_prompt = (
                updated_system_prompt
                if updated_system_prompt is not None
                else self._prefix_snapshot.system_prompt
            )
            ws_skeleton = (
                updated_workspace_skeleton
                if updated_workspace_skeleton is not None
                else self._prefix_snapshot.frozen_workspace_skeleton
            )
            self._prefix_snapshot = self._build_prefix_snapshot(
                sys_prompt, ws_skeleton
            )
            hit_ratio = 0.0
        else:
            self._cache_preserved_count += 1
            # Calculate projected KV cache hit ratio
            prefix_len = len(self._prefix_snapshot.full_prefix_text)
            body_len = len(conversation_body)
            patch_len = len(patch.formatted_tail_diff)
            total_len = prefix_len + body_len + patch_len
            hit_ratio = (prefix_len / total_len) if total_len > 0 else 1.0

        # Assemble full prompt text: Static Core Prefix -> Conversation Body -> Tail Patch
        sections: list[str] = [self._prefix_snapshot.full_prefix_text]
        if conversation_body.strip():
            sections.append(f"=== Conversation Flow ===\n{conversation_body}")
        if patch.formatted_tail_diff.strip():
            sections.append(patch.formatted_tail_diff)

        full_prompt = "\n\n".join(sections)

        return StitchedContextAssembly(
            prefix_snapshot=self._prefix_snapshot,
            conversation_body=conversation_body,
            tail_patch=patch,
            full_prompt_text=full_prompt,
            cache_hit_ratio_projected=round(hit_ratio, 4),
        )

    def cache_preservation_stats(self) -> dict[str, float]:
        """Export metrics on cache preservation frequency."""
        ratio = (
            (self._cache_preserved_count / self._total_stitches_count)
            if self._total_stitches_count > 0
            else 1.0
        )
        return {
            "total_stitches": float(self._total_stitches_count),
            "preserved_stitches": float(self._cache_preserved_count),
            "preservation_rate": round(ratio, 4),
        }

    @staticmethod
    def _build_prefix_snapshot(
        system_prompt: str,
        workspace_skeleton: str,
    ) -> StaticPrefixSnapshot:
        prefix_id = f"pfx_{uuid.uuid4().hex[:8]}"
        content = f"{system_prompt}\n{workspace_skeleton}"
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        return StaticPrefixSnapshot(
            prefix_id=prefix_id,
            system_prompt=system_prompt,
            frozen_workspace_skeleton=workspace_skeleton,
            content_hash=content_hash,
            created_at_ms=int(time.time() * 1000),
        )
