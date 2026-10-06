# [POS] tests/toolkits/memory/test_openclaw_adapter.py
# [INPUT] pytest, tempfile, sqlite3, pathlib.Path, json, myrm_agent_harness.toolkits.memory.openclaw_adapter
# [OUTPUT] TestOpenClawAdapterSuite

import json
import sqlite3
import tempfile
from pathlib import Path

from myrm_agent_harness.toolkits.memory.openclaw_adapter import (
    OpenClawCrashRescuer,
    OpenClawParsedBundle,
    OpenClawV2Parser,
    OpenClawVersion,
)


def test_v2_parser_payload_dict_swarm_and_memories() -> None:
    """Verify OpenClawV2Parser correctly converts raw dictionary payload with Swarm hierarchy."""
    parser = OpenClawV2Parser()

    payload: dict[str, object] = {
        "openclaw_v2_sessions": [
            {
                "session_id": "sess-root",
                "title": "Main Coordinator Session",
                "owner_id": "user_alice",
                "creator_id": "system_bootstrap",
                "messages": [{"role": "user", "content": "Analyze system requirements"}],
                "created_at": "2026-09-03T10:00:00Z",
            },
            {
                "session_id": "sess-swarm-1",
                "title": "Subagent Coding Swarm Worker",
                "parent_session_id": "sess-root",
                "swarm_agent_id": "worker_coder_01",
                "owner_id": "user_alice",
                "creator_id": "sess-root",
                "messages": [{"role": "assistant", "content": "Refactoring module AST"}],
                "created_at": "2026-09-03T10:05:00Z",
            },
        ],
        "openclaw_v2_memories": [
            {
                "entry_id": "mem-v2-1",
                "content": "User prefers strict PEP8 and no Any types.",
                "category": "preference",
                "scope": "private",
                "target_agent_id": "worker_coder_01",
                "importance": 0.9,
                "created_at": "2026-09-03T10:00:00Z",
            },
            {
                "entry_id": "mem-v2-2",
                "content": "Architecture baseline enforced at 724 entries.",
                "category": "fact",
                "scope": "shared",
                "importance": 0.8,
                "created_at": "2026-09-03T10:02:00Z",
            },
        ],
    }

    bundle: OpenClawParsedBundle = parser.parse_payload_dict(payload)
    assert bundle.version == OpenClawVersion.V2
    assert len(bundle.sessions) == 2
    assert len(bundle.memories) == 2

    # Check root vs child swarm session lineage
    root_node = bundle.sessions[0]
    assert root_node.session_id == "sess-root"
    assert root_node.parent_session_id is None

    child_node = bundle.sessions[1]
    assert child_node.session_id == "sess-swarm-1"
    assert child_node.parent_session_id == "sess-root"
    assert child_node.swarm_agent_id == "worker_coder_01"

    # Check memories
    mem1 = bundle.memories[0]
    assert mem1.scope == "private"
    assert mem1.target_agent_id == "worker_coder_01"
    assert mem1.importance == 0.9

    mem2 = bundle.memories[1]
    assert mem2.scope == "shared"


def test_crash_rescuer_healthy_sqlite_database() -> None:
    """Verify OpenClawCrashRescuer probes and extracts data from a healthy SQLite database."""
    rescuer = OpenClawCrashRescuer()

    with tempfile.TemporaryDirectory() as td:
        db_path = Path(td) / "openclaw_test.sqlite"
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()

        # Create v2 tables
        cursor.execute(
            """
            CREATE TABLE openclaw_v2_sessions (
                id TEXT PRIMARY KEY,
                title TEXT,
                parent_session_id TEXT,
                swarm_agent_id TEXT,
                owner_id TEXT,
                creator_id TEXT,
                messages TEXT,
                created_at TEXT
            );
            """
        )
        cursor.execute(
            """
            CREATE TABLE openclaw_v2_memories (
                id TEXT PRIMARY KEY,
                content TEXT,
                category TEXT,
                scope TEXT,
                target_agent_id TEXT,
                importance REAL,
                created_at TEXT
            );
            """
        )

        cursor.execute(
            "INSERT INTO openclaw_v2_sessions VALUES (?, ?, ?, ?, ?, ?, ?, ?);",
            (
                "sess-10",
                "Session Title 10",
                None,
                None,
                "user_bob",
                "user_bob",
                json.dumps([{"role": "user", "content": "hello"}]),
                "2026-09-03T12:00:00Z",
            ),
        )
        cursor.execute(
            "INSERT INTO openclaw_v2_memories VALUES (?, ?, ?, ?, ?, ?, ?);",
            (
                "mem-10",
                "Bob prefers dark theme.",
                "ui_pref",
                "private",
                "agent_main",
                0.85,
                "2026-09-03T12:01:00Z",
            ),
        )
        conn.commit()
        conn.close()

        # Probe integrity
        is_corrupt, output = rescuer.probe_integrity(db_path)
        assert is_corrupt is False
        assert "ok" in output.lower()

        # Extract sessions
        rows, report = rescuer.rescue_table_rows(
            db_path=db_path,
            table_name="openclaw_v2_sessions",
            expected_columns=["id", "title", "messages", "owner_id"],
        )
        assert len(rows) == 1
        assert rows[0]["id"] == "sess-10"
        assert rows[0]["owner_id"] == "user_bob"
        assert report.is_sqlite_corrupt is False
        assert report.recovered_count == 1
        assert report.rescue_success_rate == 1.0


def test_v2_parser_parse_and_rescue_sqlite() -> None:
    """Verify OpenClawV2Parser parses SQLite database directly with automatic extraction."""
    parser = OpenClawV2Parser()

    with tempfile.TemporaryDirectory() as td:
        db_path = Path(td) / "openclaw_live.sqlite"
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()

        cursor.execute(
            """
            CREATE TABLE openclaw_v2_sessions (
                id TEXT PRIMARY KEY,
                title TEXT,
                parent_session_id TEXT,
                swarm_agent_id TEXT,
                owner_id TEXT,
                creator_id TEXT,
                messages TEXT,
                created_at TEXT
            );
            """
        )
        cursor.execute(
            """
            CREATE TABLE openclaw_v2_memories (
                id TEXT PRIMARY KEY,
                content TEXT,
                category TEXT,
                scope TEXT,
                target_agent_id TEXT,
                importance REAL,
                created_at TEXT
            );
            """
        )

        cursor.execute(
            "INSERT INTO openclaw_v2_sessions VALUES (?, ?, ?, ?, ?, ?, ?, ?);",
            (
                "sess-swarm-99",
                "Swarm Worker Node",
                "sess-root-1",
                "worker_99",
                "user_charlie",
                "sess-root-1",
                json.dumps([{"content": "Completed ETL step"}]),
                "2026-09-03T15:00:00Z",
            ),
        )
        cursor.execute(
            "INSERT INTO openclaw_v2_memories VALUES (?, ?, ?, ?, ?, ?, ?);",
            (
                "mem-99",
                "ETL pipeline output location is /var/data/lake",
                "infra",
                "shared",
                None,
                0.95,
                "2026-09-03T15:01:00Z",
            ),
        )
        conn.commit()
        conn.close()

        bundle = parser.parse_and_rescue_sqlite(db_path)
        assert bundle.version == OpenClawVersion.V2
        assert len(bundle.sessions) == 1
        assert bundle.sessions[0].session_id == "sess-swarm-99"
        assert bundle.sessions[0].parent_session_id == "sess-root-1"
        assert len(bundle.memories) == 1
        assert bundle.memories[0].entry_id == "mem-99"
        assert bundle.memories[0].scope == "shared"
        assert bundle.rescue_report is not None
        assert bundle.rescue_report.recovered_count == 2


def test_crash_rescuer_corrupted_file_handling() -> None:
    """Ensure crash rescuer gracefully diagnoses malformed file and handles corruption."""
    rescuer = OpenClawCrashRescuer()

    with tempfile.TemporaryDirectory() as td:
        corrupted_path = Path(td) / "broken_corrupt.sqlite"
        # Write corrupted garbage bytes that fail SQLite header verification
        corrupted_path.write_bytes(b"NOT A REAL SQLITE DATABASE HEADER GIBBERISH" * 50)

        is_corrupt, output = rescuer.probe_integrity(corrupted_path)
        assert is_corrupt is True
        assert output != ""

        # Attempt table extraction should not crash and return empty recovered list with report
        rows, report = rescuer.rescue_table_rows(
            db_path=corrupted_path,
            table_name="openclaw_v2_sessions",
            expected_columns=["id", "title"],
        )
        assert len(rows) == 0
        assert report.is_sqlite_corrupt is True
        assert report.recovered_count == 0
