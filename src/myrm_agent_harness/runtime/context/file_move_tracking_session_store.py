"""Persistent file-move tracking session store with stable ChatId invariants.

Inspired by HermesOffice project-store. Maintains stable ChatIds across
file renames, moves, and directory reorganizations with append-only JSONL logs.
"""

import contextlib
import json
import os
import time
import uuid

from myrm_agent_harness.runtime.context.file_move_tracking_store_types import (
    ChatMessageEntry,
    ChatMetaSnapshot,
    FileTrackResolution,
)


class PersistentFileMoveTrackingSessionStore:
    """Session store binding conversation history to files with rename/move tracking."""

    def __init__(self, store_dir: str) -> None:
        self._store_dir = os.path.abspath(store_dir)
        self._sessions_dir = os.path.join(self._store_dir, "sessions")
        self._index_file = os.path.join(self._store_dir, "project_index.json")

        self._chat_id_by_path: dict[str, str] = {}
        self._history_path_map: dict[str, str] = {}
        self._metas: dict[str, ChatMetaSnapshot] = {}

        os.makedirs(self._sessions_dir, exist_ok=True)
        self._load_index()

    def normalize_path(self, path: str) -> str:
        """Normalize file path representation consistently."""
        clean = os.path.normpath(path).replace("\\", "/")
        return clean.rstrip("/")

    def resolve_chat_id_for_path(
        self, path: str, title: str = ""
    ) -> FileTrackResolution:
        """Resolve a file path to its stable ChatId, creating one if not exists."""
        norm_path = self.normalize_path(path)
        now = time.time()

        # 1. Direct path hit
        if norm_path in self._chat_id_by_path:
            c_id = self._chat_id_by_path[norm_path]
            return FileTrackResolution(
                chat_id=c_id,
                bound_path=norm_path,
                is_newly_created=False,
                matched_via_history=False,
            )

        # 2. Historical path hit
        if norm_path in self._history_path_map:
            c_id = self._history_path_map[norm_path]
            self._chat_id_by_path[norm_path] = c_id
            self._save_index()
            return FileTrackResolution(
                chat_id=c_id,
                bound_path=norm_path,
                is_newly_created=False,
                matched_via_history=True,
            )

        # 3. New registration
        new_id = f"chat-{uuid.uuid4().hex[:12]}"
        self._chat_id_by_path[norm_path] = new_id
        meta = ChatMetaSnapshot(
            chat_id=new_id,
            bound_path=norm_path,
            title=title or os.path.basename(norm_path),
            message_count=0,
            created_at=now,
            last_active_at=now,
            path_history=[norm_path],
        )
        self._metas[new_id] = meta
        self._save_index()

        return FileTrackResolution(
            chat_id=new_id,
            bound_path=norm_path,
            is_newly_created=True,
            matched_via_history=False,
        )

    def track_file_moved(
        self, old_path: str, new_path: str, is_directory: bool = False
    ) -> list[str]:
        """Atomically migrate ChatId bindings when a file or directory is moved."""
        norm_old = self.normalize_path(old_path)
        norm_new = self.normalize_path(new_path)
        affected_chat_ids: list[str] = []

        if is_directory:
            prefix_old = norm_old + "/"
            matched_paths = [
                p
                for p in self._chat_id_by_path
                if p == norm_old or p.startswith(prefix_old)
            ]
            for p in matched_paths:
                sub_rel = p[len(norm_old) :]
                migrated_new = norm_new + sub_rel
                c_id = self._migrate_single_path(p, migrated_new)
                if c_id:
                    affected_chat_ids.append(c_id)
        else:
            c_id = self._migrate_single_path(norm_old, norm_new)
            if c_id:
                affected_chat_ids.append(c_id)

        if affected_chat_ids:
            self._save_index()
        return affected_chat_ids

    def append_message(
        self,
        chat_id: str,
        role: str,
        content: str,
        metadata: dict[str, str] | None = None,
    ) -> ChatMessageEntry:
        """Append a message to the session's JSONL file and update metadata snapshot."""
        now = time.time()
        entry_id = f"msg-{uuid.uuid4().hex[:8]}"
        entry = ChatMessageEntry(
            entry_id=entry_id,
            role=role,
            content=content,
            timestamp=now,
            metadata=metadata or {},
        )

        session_file = os.path.join(self._sessions_dir, f"{chat_id}.jsonl")
        line_data = {
            "entry_id": entry.entry_id,
            "role": entry.role,
            "content": entry.content,
            "timestamp": entry.timestamp,
            "metadata": entry.metadata,
        }
        with open(session_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(line_data) + "\n")

        # Update metadata snapshot
        if chat_id in self._metas:
            old_m = self._metas[chat_id]
            self._metas[chat_id] = ChatMetaSnapshot(
                chat_id=old_m.chat_id,
                bound_path=old_m.bound_path,
                title=old_m.title,
                message_count=old_m.message_count + 1,
                created_at=old_m.created_at,
                last_active_at=now,
                path_history=old_m.path_history,
            )
            self._save_index()

        return entry

    def load_messages(
        self, chat_id: str, limit: int | None = None
    ) -> list[ChatMessageEntry]:
        """Load conversation entries from session JSONL file."""
        session_file = os.path.join(self._sessions_dir, f"{chat_id}.jsonl")
        if not os.path.exists(session_file):
            return []

        entries: list[ChatMessageEntry] = []
        with open(session_file, encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                d = json.loads(line)
                entries.append(
                    ChatMessageEntry(
                        entry_id=d["entry_id"],
                        role=d["role"],
                        content=d["content"],
                        timestamp=d["timestamp"],
                        metadata=d.get("metadata", {}),
                    )
                )

        if limit is not None and limit > 0:
            return entries[-limit:]
        return entries

    def get_chat_meta(self, chat_id: str) -> ChatMetaSnapshot | None:
        """Get metadata snapshot for a ChatId."""
        return self._metas.get(chat_id)

    def list_all_chat_metas(self) -> list[ChatMetaSnapshot]:
        """List all session metadata snapshots sorted by last_active_at descending."""
        return sorted(
            self._metas.values(), key=lambda m: m.last_active_at, reverse=True
        )

    def delete_chat(self, chat_id: str) -> bool:
        """Delete session data, metadata, and path mappings."""
        if chat_id not in self._metas:
            return False

        meta = self._metas.pop(chat_id)
        if meta.bound_path in self._chat_id_by_path:
            del self._chat_id_by_path[meta.bound_path]
        for h in meta.path_history:
            if h in self._history_path_map:
                del self._history_path_map[h]

        session_file = os.path.join(self._sessions_dir, f"{chat_id}.jsonl")
        if os.path.exists(session_file):
            with contextlib.suppress(OSError):
                os.remove(session_file)

        self._save_index()
        return True

    def _migrate_single_path(
        self, norm_old: str, norm_new: str
    ) -> str | None:
        if norm_old not in self._chat_id_by_path:
            return None

        c_id = self._chat_id_by_path.pop(norm_old)
        self._chat_id_by_path[norm_new] = c_id
        self._history_path_map[norm_old] = c_id

        if c_id in self._metas:
            old_m = self._metas[c_id]
            updated_hist = list(old_m.path_history)
            if norm_new not in updated_hist:
                updated_hist.append(norm_new)
            self._metas[c_id] = ChatMetaSnapshot(
                chat_id=old_m.chat_id,
                bound_path=norm_new,
                title=os.path.basename(norm_new),
                message_count=old_m.message_count,
                created_at=old_m.created_at,
                last_active_at=time.time(),
                path_history=updated_hist,
            )
        return c_id

    def _save_index(self) -> None:
        data = {
            "chat_id_by_path": self._chat_id_by_path,
            "history_path_map": self._history_path_map,
            "metas": {
                c_id: {
                    "chat_id": m.chat_id,
                    "bound_path": m.bound_path,
                    "title": m.title,
                    "message_count": m.message_count,
                    "created_at": m.created_at,
                    "last_active_at": m.last_active_at,
                    "path_history": m.path_history,
                }
                for c_id, m in self._metas.items()
            },
        }
        with open(self._index_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def _load_index(self) -> None:
        if not os.path.exists(self._index_file):
            return
        try:
            with open(self._index_file, encoding="utf-8") as f:
                data = json.load(f)
            self._chat_id_by_path = data.get("chat_id_by_path", {})
            self._history_path_map = data.get("history_path_map", {})
            metas_dict = data.get("metas", {})
            self._metas = {
                c_id: ChatMetaSnapshot(**m_data)
                for c_id, m_data in metas_dict.items()
            }
        except (OSError, json.JSONDecodeError):
            pass
