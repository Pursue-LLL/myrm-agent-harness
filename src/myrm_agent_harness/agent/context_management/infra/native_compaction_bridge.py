"""Native compaction bridge & sidecar checkpoint manager.

[INPUT]
- infra.atomic_write::async_atomic_write (POS: crash-safe atomic JSON write)
- toolkits.llms.adapters.native_compaction::NativeCompactionItem (POS: compaction DTO)
- infra.schemas::ContextPreCompactCallback (POS: memory recall hook)

[OUTPUT]
- NativeCompactionSidecarStore: Local crash-safe checkpoint cache
- NativeCompactionCoordinator: Manages dual-track lifecycle, threshold margin & boundary hooks

[POS]
Harness context management infrastructure for OpenAI server-side compaction.
Coordinates threshold margin (Server < Local), boundary hook firing for MemoryPreCompact,
and atomic sidecar persistence for seamless model switching without memory loss.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from myrm_agent_harness.infra.atomic_write import async_atomic_write
from myrm_agent_harness.toolkits.llms.adapters.native_compaction import NativeCompactionItem

logger = logging.getLogger(__name__)

# Server-side compaction threshold is clamped below local threshold by default
LOCAL_TRIGGER_SAFETY_MARGIN_RATIO: float = 0.85
DEFAULT_SERVER_COMPACT_THRESHOLD: int = 200_000
MIN_SERVER_COMPACT_THRESHOLD: int = 50_000


class NativeCompactionSidecarStore:
    """Crash-safe local store for native encrypted compaction checkpoints."""

    def __init__(self, base_dir: Path | str | None = None) -> None:
        self.base_dir = Path(base_dir) if base_dir else Path(".context/native_checkpoints")

    def _get_path(self, session_id: str) -> Path:
        return self.base_dir / f"{session_id}.json"

    async def save_checkpoint(self, session_id: str, item: NativeCompactionItem) -> None:
        """Atomically persist an encrypted compaction item."""
        if not session_id:
            return
        target = self._get_path(session_id)
        try:
            payload = json.dumps(item.to_dict(), ensure_ascii=False, indent=2)
            await async_atomic_write(target, payload)
        except Exception as e:
            logger.warning("Failed to persist native compaction sidecar for session %s: %s", session_id, e)

    def load_checkpoint(self, session_id: str) -> NativeCompactionItem | None:
        """Load encrypted compaction item with corrupted file self-healing."""
        if not session_id:
            return None
        target = self._get_path(session_id)
        if not target.exists():
            return None

        try:
            data = json.loads(target.read_text(encoding="utf-8"))
            return NativeCompactionItem(
                item_id=str(data.get("id") or data.get("item_id") or ""),
                encrypted_payload=str(data.get("encrypted_payload") or ""),
                created_at=int(data.get("created_at") or 0),
                compact_threshold=int(data.get("compact_threshold") or DEFAULT_SERVER_COMPACT_THRESHOLD),
                model=str(data.get("model") or ""),
            )
        except Exception as e:
            logger.warning("Corrupted native compaction sidecar for session %s, discarding: %s", session_id, e)
            try:
                target.unlink(missing_ok=True)
            except Exception:
                pass
            return None

    def delete_checkpoint(self, session_id: str) -> None:
        """Remove checkpoint file if session reset or invalidated."""
        if not session_id:
            return
        target = self._get_path(session_id)
        target.unlink(missing_ok=True)


class NativeCompactionCoordinator:
    """Coordinates server-side compaction safety margin, boundary hooks, and fallback state."""

    def __init__(
        self,
        sidecar_store: NativeCompactionSidecarStore | None = None,
    ) -> None:
        self.sidecar_store = sidecar_store or NativeCompactionSidecarStore()
        self._disabled_sessions: set[str] = set()

    def calculate_clamped_server_threshold(
        self,
        local_threshold: int,
        requested_server_threshold: int = DEFAULT_SERVER_COMPACT_THRESHOLD,
    ) -> int:
        """Clamp server threshold safely below local compression trigger."""
        margin_ceiling = int(local_threshold * LOCAL_TRIGGER_SAFETY_MARGIN_RATIO)
        clamped = min(requested_server_threshold, margin_ceiling)
        return max(MIN_SERVER_COMPACT_THRESHOLD, clamped)

    def is_session_native_enabled(self, session_id: str) -> bool:
        """Check if native compaction is active and not disabled by one-shot recovery."""
        return session_id not in self._disabled_sessions

    def mark_session_rejection_fallback(self, session_id: str, reason: str = "") -> None:
        """Disable native compaction for this session on 400/422 rejection and fallback to local."""
        if session_id:
            self._disabled_sessions.add(session_id)
            self.sidecar_store.delete_checkpoint(session_id)
            logger.info(
                "One-shot rejection recovery: native compaction disabled for session %s (reason: %s)",
                session_id,
                reason,
            )

    async def on_native_compaction_detected(
        self,
        session_id: str,
        item: NativeCompactionItem,
        pre_compact_hook: Any | None = None,
    ) -> None:
        """Handle server-side compaction event: persist sidecar & fire MemoryPreCompact hook."""
        await self.sidecar_store.save_checkpoint(session_id, item)
        logger.info(
            "Native compaction checkpoint recorded for session %s (item_id: %s)",
            session_id,
            item.item_id,
        )

        if pre_compact_hook is not None:
            try:
                # Trigger memory pre-compaction recall so durable memories are safe
                if hasattr(pre_compact_hook, "recall_and_persist"):
                    cb = getattr(pre_compact_hook, "recall_and_persist")
                    res = cb(session_id=session_id)
                    import inspect

                    if inspect.isawaitable(res):
                        await res
                elif callable(pre_compact_hook):
                    import inspect

                    res = pre_compact_hook(session_id=session_id)
                    if inspect.isawaitable(res):
                        await res
            except Exception as e:
                logger.warning("Error running pre_compact_hook on native compaction: %s", e)
