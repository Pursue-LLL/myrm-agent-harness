"""Tracker for memory snapshot staleness, dirty flags, and intra-session delta patching.

[INPUT]
- Session initializations, disk write mutation records, and lookup queries.

[OUTPUT]
- MemorySnapshotDigest, DirectDiskReadHint, and DeltaPatchBlock instances.

[POS]
- Harness framework core tracker for Item 157 SnapshotLagAwareMemoryFreshnessAndDiskVerificationContractSuite.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from myrm_agent_harness.agent.middlewares.memory_context.snapshot_freshness.models import (
    DeltaPatchBlock,
    DirectDiskReadHint,
    MemorySnapshotDigest,
    SessionWriteDelta,
    SnapshotFreshnessState,
    WriteActionType,
)


class SnapshotFreshnessTracker:
    """Manages memory snapshot generation digests, dirty state tracking, and delta patches."""

    def __init__(self) -> None:
        self._states: dict[str, SnapshotFreshnessState] = {}

    def init_session_snapshot(
        self,
        session_id: str,
        initial_content: str = "",
        items_count: int = 0,
    ) -> MemorySnapshotDigest:
        """Initialize and seal the initial memory snapshot digest for a new or restored session."""
        now_iso = datetime.now(UTC).isoformat()
        hasher = hashlib.sha256()
        hasher.update(session_id.encode("utf-8"))
        hasher.update(initial_content.encode("utf-8"))
        hasher.update(now_iso.encode("utf-8"))
        digest_hex = f"snap_{hasher.hexdigest()[:12]}"

        digest = MemorySnapshotDigest(
            digest=digest_hex,
            session_id=session_id,
            created_at=now_iso,
            initial_items_count=items_count,
        )

        self._states[session_id] = SnapshotFreshnessState(
            session_id=session_id,
            snapshot_digest=digest_hex,
            is_dirty=False,
            deltas=[],
            latest_disk_version=1,
        )
        return digest

    def record_write(
        self,
        session_id: str,
        key: str,
        content: str,
        turn_index: int = 0,
        action: WriteActionType = "update",
    ) -> SnapshotFreshnessState:
        """Record an ongoing memory write event to disk and mark snapshot as dirty."""
        now_iso = datetime.now(UTC).isoformat()
        state = self._states.get(session_id)
        if state is None:
            # Auto-initialize fallback if write precedes explicit snapshot init
            state = SnapshotFreshnessState(
                session_id=session_id,
                snapshot_digest=f"snap_auto_{session_id[:8]}",
                is_dirty=False,
                deltas=[],
                latest_disk_version=1,
            )
            self._states[session_id] = state

        delta = SessionWriteDelta(
            key=key,
            content=content,
            turn_index=turn_index,
            written_at=now_iso,
            action=action,
        )

        # Upsert delta by key to preserve latest mutation
        filtered_deltas = [d for d in state.deltas if d.key != key]
        filtered_deltas.append(delta)

        state.deltas = filtered_deltas
        state.is_dirty = True
        state.latest_disk_version += 1
        return state

    def get_state(self, session_id: str) -> SnapshotFreshnessState:
        """Retrieve the freshness state for a session, creating default if missing."""
        if session_id not in self._states:
            self._states[session_id] = SnapshotFreshnessState(
                session_id=session_id,
                snapshot_digest="snap_empty",
                is_dirty=False,
                deltas=[],
                latest_disk_version=1,
            )
        return self._states[session_id]

    def generate_disk_read_hint(self, session_id: str) -> DirectDiskReadHint:
        """Generate a contract hint prompting the model to verify persistent disk truth."""
        state = self.get_state(session_id)
        affected_keys = [d.key for d in state.deltas]

        if not state.is_dirty:
            return DirectDiskReadHint(
                session_id=session_id,
                hint_message="当前会话记忆快照与磁盘持久层完全一致，未发生跨轮脏写入。",
                affected_keys=[],
                is_dirty=False,
            )

        keys_summary = ", ".join(affected_keys)
        hint_message = (
            f"【记忆快照感知契约】当前上下文中的记忆区块为会话启动时快照（版本: {state.snapshot_digest}）。"
            f"当前会话已有 {len(affected_keys)} 项最新事实落盘写入（涉及键/实体: {keys_summary}）。"
            f"若需验证最新事实或消除矛盾，请优先直接调用内存查询工具读取底层持久磁盘，切勿仅依赖上下文旧快照。"
        )

        return DirectDiskReadHint(
            session_id=session_id,
            hint_message=hint_message,
            affected_keys=affected_keys,
            is_dirty=True,
        )

    def render_delta_patch(self, session_id: str) -> DeltaPatchBlock:
        """Render intra-session memory delta patch block for append-only prompt injection."""
        state = self.get_state(session_id)
        if not state.is_dirty or not state.deltas:
            return DeltaPatchBlock(
                header="[SESSION MEMORY DELTA PATCH - EMPTY]",
                patches=[],
                formatted_block="",
            )

        header = f"### [SESSION MEMORY DELTA PATCH - DISK VERIFIED v{state.latest_disk_version}]"
        patch_lines: list[str] = []
        for d in state.deltas:
            action_tag = d.action.upper()
            patch_lines.append(
                f"- [{action_tag}] `{d.key}`: {d.content} (落盘轮次: T{d.turn_index})"
            )

        block_lines = [
            header,
            "注意：以下条目已在当前会话中成功持久化落盘，其真实性严格覆盖系统初始快照：",
            *patch_lines,
        ]
        formatted_block = "\n".join(block_lines)

        return DeltaPatchBlock(
            header=header,
            patches=patch_lines,
            formatted_block=formatted_block,
        )

    def reset_session(self, session_id: str) -> None:
        """Clear tracking state for a finished or wiped session."""
        if session_id in self._states:
            del self._states[session_id]
