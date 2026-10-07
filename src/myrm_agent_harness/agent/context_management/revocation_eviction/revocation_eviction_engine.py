"""Core engine for Context Sanitization and Memory Eviction Upon Revocation.

[INPUT]
- revocation_eviction_types: Models for scopes, taint traces, directives, and outcomes.

[OUTPUT]
- RevocationEvictionEngine: Surgical context purging and working memory eviction coordinator.

[POS]
Executes line-item sensitive data expunging from in-memory context and short-term memory partitions,
preventing cross-turn data leaks after administrative permission revocation.
"""

from __future__ import annotations

import copy
import time

from myrm_agent_harness.agent.context_management.revocation_eviction.revocation_eviction_types import (
    RevocationDirective,
    RevocationScopeKind,
    SanitizationOutcome,
    TaintedContentBlock,
)


class RevocationEvictionEngine:
    """Coordinates lineage taint tracking, surgical context sanitization, and memory eviction."""

    def __init__(self) -> None:
        # Maps scope_id to list of registered tainted content blocks
        self._taint_registry: dict[str, list[TaintedContentBlock]] = {}

    def register_tainted_block(
        self,
        block_id: str,
        turn_index: int,
        scope_kind: RevocationScopeKind,
        scope_id: str,
        resource_name: str,
        char_count: int,
    ) -> TaintedContentBlock:
        """Records a sensitive data block with its governing permission scope."""
        block = TaintedContentBlock(
            block_id=block_id,
            turn_index=turn_index,
            scope_kind=scope_kind,
            scope_id=scope_id,
            resource_name=resource_name,
            char_count=char_count,
            created_at=time.time(),
        )
        blocks = self._taint_registry.setdefault(scope_id, [])
        blocks.append(block)
        return block

    @staticmethod
    def _sanitize_message_content(
        msg: dict[str, object], resource_name: str, scope_id: str
    ) -> bool:
        """Physically expunges sensitive payload from a single message, returning True if altered."""
        placeholder = (
            f"[Data Expunged: Access to '{resource_name}' (Scope: {scope_id}) "
            "was revoked. Content purged by governance policy.]"
        )
        modified = False

        content = msg.get("content")
        if isinstance(content, str):
            msg["content"] = placeholder
            modified = True
        elif isinstance(content, list):
            # If content is a list of blocks, replace with a single text placeholder block
            msg["content"] = [{"type": "text", "text": placeholder}]
            modified = True

        # Clean tool outputs / args if present
        if "tool_calls" in msg:
            msg["tool_calls"] = []
            modified = True

        return modified

    def execute_surgical_revocation(
        self,
        messages: list[dict[str, object]],
        directive: RevocationDirective,
        working_memory_entries: list[dict[str, object]] | None = None,
    ) -> tuple[SanitizationOutcome, list[dict[str, object]]]:
        """Surgically purges all message turns and memory items linked to the revoked scope."""
        start_time = time.perf_counter()
        scope_id = directive.scope_id
        tainted_blocks = self._taint_registry.pop(scope_id, [])

        audit_trail: list[str] = [
            f"Revocation initiated for scope '{scope_id}' (Reason: {directive.reason})"
        ]

        cleansed_messages: list[dict[str, object]] = copy.deepcopy(messages)
        sanitized_turns: set[int] = set()
        purged_blocks_count = 0

        # 1. Surgical in-place replacement of matching message turns
        turn_to_resource: dict[int, str] = {
            b.turn_index: b.resource_name for b in tainted_blocks
        }

        for turn_idx, res_name in turn_to_resource.items():
            if 0 <= turn_idx < len(cleansed_messages):
                altered = self._sanitize_message_content(
                    cleansed_messages[turn_idx], res_name, scope_id
                )
                if altered:
                    sanitized_turns.add(turn_idx)
                    audit_trail.append(
                        f"Purged turn {turn_idx}: expunged sensitive resource '{res_name}'"
                    )

        purged_blocks_count = len(tainted_blocks)

        # 2. Evict matching entries from working memory / scratchpad
        cleansed_memory: list[dict[str, object]] = []
        evicted_memory_count = 0

        if working_memory_entries is not None and directive.evict_working_memory:
            for entry in working_memory_entries:
                entry_scope = entry.get("scope_id") or entry.get("scope") or ""
                resource = entry.get("resource_name") or ""
                content_str = str(entry.get("content") or entry.get("fact") or "")

                # If entry belongs to revoked scope or matches resource name, evict
                if entry_scope == scope_id or (res_name and res_name in content_str):
                    evicted_memory_count += 1
                    audit_trail.append(
                        f"Evicted working memory entry associated with scope '{scope_id}'"
                    )
                else:
                    cleansed_memory.append(copy.deepcopy(entry))
        elif working_memory_entries is not None:
            cleansed_memory = copy.deepcopy(working_memory_entries)

        duration_ms = (time.perf_counter() - start_time) * 1000.0

        outcome = SanitizationOutcome(
            revocation_id=directive.revocation_id,
            scope_id=scope_id,
            sanitized_turns_count=len(sanitized_turns),
            purged_blocks_count=purged_blocks_count,
            evicted_memory_entries_count=evicted_memory_count,
            cleansed_messages=cleansed_messages,
            audit_trail=audit_trail,
            duration_ms=duration_ms,
        )

        return outcome, cleansed_memory

    def get_registered_taints_for_scope(
        self, scope_id: str
    ) -> list[TaintedContentBlock]:
        """Returns active taint registrations for a given scope."""
        return list(self._taint_registry.get(scope_id, []))
