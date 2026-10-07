"""Core engine for Lossless Context Pivot and Scratchpad Reset Suite.

[INPUT]
- context_pivot_types: Contracts for handoff scratchpads, archived snapshots, and pivot results.

[OUTPUT]
- LosslessContextPivotEngine: Zero-compaction context wipe and scratchpad continuation orchestrator.

[POS]
Executes clean window resets by archiving full conversation history to storage,
injecting structured phase handoff scratchpads, and eliminating progressive summarization distortion.
"""

from __future__ import annotations

import copy
import time
import uuid

from myrm_agent_harness.agent.context_management.context_pivot.context_pivot_types import (
    ArchivedContextSnapshot,
    ContextPivotConfig,
    ContextPivotResult,
    HandoffScratchpad,
    PivotTriggerKind,
)


class LosslessContextPivotEngine:
    """Orchestrates zero-compaction clean window pivots with structured scratchpad continuation."""

    def __init__(self, default_config: ContextPivotConfig | None = None) -> None:
        self._default_config = default_config or ContextPivotConfig()
        # Maps session_id to list of (snapshot_meta, original_messages_copy)
        self._archive_store: dict[str, list[tuple[ArchivedContextSnapshot, list[dict[str, object]]]]] = {}
        # Maps session_id to latest active scratchpad
        self._active_scratchpads: dict[str, HandoffScratchpad] = {}

    def pivot_to_clean_context(
        self,
        session_id: str,
        current_messages: list[dict[str, object]],
        scratchpad: HandoffScratchpad,
        base_system_prompt: str = "You are an expert autonomous AI agent.",
        config: ContextPivotConfig | None = None,
    ) -> ContextPivotResult:
        """Wipes active conversation context, archives history, and initializes a clean workbench."""
        start_time = time.perf_counter()
        cfg = config or self._default_config

        # 1. Calculate pre-pivot footprint
        prior_msg_count = len(current_messages)
        prior_chars = sum(len(str(m.get("content", ""))) for m in current_messages)
        prior_tokens = max(1, prior_chars // 4)

        # 2. Archive existing context to persistent storage
        snapshot_id = f"snap_{uuid.uuid4().hex[:12]}"
        now = time.time()
        snapshot_meta = ArchivedContextSnapshot(
            snapshot_id=snapshot_id,
            session_id=session_id,
            phase_title=scratchpad.phase_title,
            message_count=prior_msg_count,
            char_count=prior_chars,
            archived_at=now,
        )

        session_archives = self._archive_store.setdefault(session_id, [])
        session_archives.append((snapshot_meta, copy.deepcopy(current_messages)))
        self._active_scratchpads[session_id] = copy.deepcopy(scratchpad)

        # 3. Assemble clean context
        scratchpad_xml = scratchpad.format_xml()
        clean_system_prompt = (
            f"{base_system_prompt.strip()}\n\n"
            "=== ACTIVE PHASE HANDOFF SCRATCHPAD ===\n"
            f"{scratchpad_xml}"
        )

        clean_messages: list[dict[str, object]] = [
            {"role": "system", "content": clean_system_prompt}
        ]

        if cfg.inject_continuation_user_prompt:
            user_msg = cfg.continuation_prompt_template.format(phase=scratchpad.phase_title)
            clean_messages.append({"role": "user", "content": user_msg})

        # 4. Calculate reclaimed tokens
        clean_chars = sum(len(str(m.get("content", ""))) for m in clean_messages)
        clean_tokens = max(1, clean_chars // 4)
        reclaimed_tokens = max(0, prior_tokens - clean_tokens)

        duration_ms = (time.perf_counter() - start_time) * 1000.0

        return ContextPivotResult(
            session_id=session_id,
            snapshot_id=snapshot_id,
            trigger_kind=cfg.trigger_kind,
            reclaimed_tokens_estimate=reclaimed_tokens,
            prior_message_count=prior_msg_count,
            clean_messages=clean_messages,
            scratchpad=scratchpad,
            pivot_duration_ms=round(duration_ms, 2),
        )

    def get_archived_snapshots(self, session_id: str) -> list[ArchivedContextSnapshot]:
        """Returns metadata list of all archived historical context generations for session."""
        records = self._archive_store.get(session_id, [])
        return [meta for meta, _ in records]

    def restore_archived_messages(
        self, session_id: str, snapshot_id: str
    ) -> list[dict[str, object]] | None:
        """Retrieves raw uncompacted message history from a specific pre-pivot generation."""
        records = self._archive_store.get(session_id, [])
        for meta, msgs in records:
            if meta.snapshot_id == snapshot_id:
                return copy.deepcopy(msgs)
        return None

    def get_latest_scratchpad(self, session_id: str) -> HandoffScratchpad | None:
        """Retrieves the active scratchpad carrying forward phase handoffs."""
        pad = self._active_scratchpads.get(session_id)
        return copy.deepcopy(pad) if pad else None

    def clear_session(self, session_id: str) -> None:
        """Cleans memory cache and archive references for a given session."""
        self._archive_store.pop(session_id, None)
        self._active_scratchpads.pop(session_id, None)
