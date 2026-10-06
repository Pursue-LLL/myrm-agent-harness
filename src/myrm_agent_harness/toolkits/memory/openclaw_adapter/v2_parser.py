# [POS] src/myrm_agent_harness/toolkits/memory/openclaw_adapter/v2_parser.py
# [INPUT] json, logging, pathlib.Path, .types, .crash_rescuer
# [OUTPUT] OpenClawV2Parser

import json
import logging
from pathlib import Path

from .crash_rescuer import OpenClawCrashRescuer
from .types import (
    OpenClawMemoryEntryV2,
    OpenClawParsedBundle,
    OpenClawSessionNode,
    OpenClawVersion,
    RescueReport,
)

logger = logging.getLogger(__name__)


class OpenClawV2Parser:
    """Parser and format adapter for OpenClaw 2.0 multi-user, Swarm topology, and structured memories."""

    def __init__(self, rescuer: OpenClawCrashRescuer | None = None) -> None:
        self.rescuer: OpenClawCrashRescuer = rescuer or OpenClawCrashRescuer()

    def parse_payload_dict(self, payload: dict[str, object]) -> OpenClawParsedBundle:
        """Parse raw memory and session dictionaries exported from OpenClaw 2.0."""
        warnings: list[str] = []
        sessions: list[OpenClawSessionNode] = []
        memories: list[OpenClawMemoryEntryV2] = []

        raw_sessions = payload.get("openclaw_v2_sessions") or payload.get("sessions")
        if isinstance(raw_sessions, list):
            for item in raw_sessions:
                if isinstance(item, dict):
                    node = self._build_session_node_from_dict(item)
                    if node is not None:
                        sessions.append(node)

        raw_memories = payload.get("openclaw_v2_memories") or payload.get("memories")
        if isinstance(raw_memories, list):
            for item in raw_memories:
                if isinstance(item, dict):
                    entry = self._build_memory_entry_from_dict(item)
                    if entry is not None:
                        memories.append(entry)

        if not sessions and not memories:
            warnings.append("no_v2_records_found")

        return OpenClawParsedBundle(
            version=OpenClawVersion.V2,
            sessions=sessions,
            memories=memories,
            rescue_report=None,
            warnings=warnings,
        )

    def parse_and_rescue_sqlite(self, db_path: Path) -> OpenClawParsedBundle:
        """Inspect and parse an OpenClaw SQLite database, automatically triggering rescue if damaged."""
        warnings: list[str] = []
        sessions: list[OpenClawSessionNode] = []
        memories: list[OpenClawMemoryEntryV2] = []

        session_cols = [
            "id",
            "title",
            "parent_session_id",
            "swarm_agent_id",
            "owner_id",
            "creator_id",
            "messages",
            "created_at",
        ]
        memory_cols = [
            "id",
            "content",
            "category",
            "scope",
            "target_agent_id",
            "importance",
            "created_at",
        ]

        # 1. Attempt extracting sessions
        session_rows, session_report = self.rescuer.rescue_table_rows(
            db_path=db_path,
            table_name="openclaw_v2_sessions",
            expected_columns=session_cols,
        )
        if not session_rows:
            # Fallback to legacy or alternative table name
            session_rows, session_report = self.rescuer.rescue_table_rows(
                db_path=db_path,
                table_name="sessions",
                expected_columns=["id", "title", "created_at"],
            )

        for row in session_rows:
            node = self._build_session_node_from_row(row)
            if node is not None:
                sessions.append(node)

        # 2. Attempt extracting memories
        memory_rows, memory_report = self.rescuer.rescue_table_rows(
            db_path=db_path,
            table_name="openclaw_v2_memories",
            expected_columns=memory_cols,
        )
        if not memory_rows:
            memory_rows, memory_report = self.rescuer.rescue_table_rows(
                db_path=db_path,
                table_name="memories",
                expected_columns=["id", "content", "created_at"],
            )

        for row in memory_rows:
            entry = self._build_memory_entry_from_row(row)
            if entry is not None:
                memories.append(entry)

        # Consolidated rescue report
        combined_report = RescueReport(
            db_path=str(db_path),
            is_sqlite_corrupt=session_report.is_sqlite_corrupt or memory_report.is_sqlite_corrupt,
            integrity_check_output=session_report.integrity_check_output,
            total_rows_scanned=session_report.total_rows_scanned + memory_report.total_rows_scanned,
            recovered_count=session_report.recovered_count + memory_report.recovered_count,
            corrupted_rows_skipped=session_report.corrupted_rows_skipped + memory_report.corrupted_rows_skipped,
            rescue_success_rate=(
                session_report.rescue_success_rate + memory_report.rescue_success_rate
            ) / 2.0,
        )

        if combined_report.is_sqlite_corrupt:
            warnings.append(f"sqlite_corrupted_salvaged_{combined_report.recovered_count}_rows")

        return OpenClawParsedBundle(
            version=OpenClawVersion.V2,
            sessions=sessions,
            memories=memories,
            rescue_report=combined_report,
            warnings=warnings,
        )

    def _build_session_node_from_dict(self, data: dict[str, object]) -> OpenClawSessionNode | None:
        sid = str(data.get("session_id") or data.get("id") or "")
        if not sid:
            return None
        title = str(data.get("title") or data.get("name") or "OpenClaw Session")
        raw_msgs = data.get("messages")
        parsed_msgs: list[dict[str, str]] = []
        if isinstance(raw_msgs, list):
            for m in raw_msgs:
                if isinstance(m, dict):
                    parsed_msgs.append({k: str(v) for k, v in m.items()})

        return OpenClawSessionNode(
            session_id=sid,
            title=title,
            parent_session_id=str(data.get("parent_session_id")) if data.get("parent_session_id") else None,
            swarm_agent_id=str(data.get("swarm_agent_id")) if data.get("swarm_agent_id") else None,
            owner_id=str(data.get("owner_id") or "default_user"),
            creator_id=str(data.get("creator_id") or "default_user"),
            messages=parsed_msgs,
            created_at=str(data.get("created_at") or ""),
        )

    def _build_memory_entry_from_dict(self, data: dict[str, object]) -> OpenClawMemoryEntryV2 | None:
        mid = str(data.get("entry_id") or data.get("id") or "")
        content = str(data.get("content") or data.get("fact") or "")
        if not content:
            return None

        scope_val = str(data.get("scope") or "shared").lower()
        if scope_val not in ("private", "shared"):
            scope_val = "shared"

        return OpenClawMemoryEntryV2(
            entry_id=mid or f"mem-v2-{len(content)}",
            content=content,
            category=str(data.get("category") or "general"),
            scope=scope_val,
            target_agent_id=str(data.get("target_agent_id")) if data.get("target_agent_id") else None,
            importance=float(data.get("importance", 0.7)),
            created_at=str(data.get("created_at") or ""),
        )

    def _build_session_node_from_row(self, row: dict[str, str]) -> OpenClawSessionNode | None:
        sid = row.get("id", "").strip()
        if not sid:
            return None
        title = row.get("title", "").strip() or "OpenClaw Session"
        raw_msgs = row.get("messages", "")
        parsed_msgs: list[dict[str, str]] = []
        if raw_msgs:
            try:
                loaded = json.loads(raw_msgs)
                if isinstance(loaded, list):
                    for item in loaded:
                        if isinstance(item, dict):
                            parsed_msgs.append({k: str(v) for k, v in item.items()})
            except Exception:
                parsed_msgs.append({"content": raw_msgs})

        return OpenClawSessionNode(
            session_id=sid,
            title=title,
            parent_session_id=row.get("parent_session_id") or None,
            swarm_agent_id=row.get("swarm_agent_id") or None,
            owner_id=row.get("owner_id") or "default_user",
            creator_id=row.get("creator_id") or "default_user",
            messages=parsed_msgs,
            created_at=row.get("created_at") or "",
        )

    def _build_memory_entry_from_row(self, row: dict[str, str]) -> OpenClawMemoryEntryV2 | None:
        mid = row.get("id", "").strip()
        content = row.get("content", "").strip()
        if not content:
            return None
        scope = row.get("scope", "shared").strip().lower()
        if scope not in ("private", "shared"):
            scope = "shared"

        return OpenClawMemoryEntryV2(
            entry_id=mid or "mem-salvaged",
            content=content,
            category=row.get("category") or "general",
            scope=scope,
            target_agent_id=row.get("target_agent_id") or None,
            importance=float(row.get("importance", "0.7")),
            created_at=row.get("created_at") or "",
        )
