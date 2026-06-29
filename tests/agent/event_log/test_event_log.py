"""Unit tests for the event log subsystem (P0-1).

Tests EventLogger (logger.py), FileEventLogBackend (file_backend.py),
and types (types.py) to ensure correct event recording, PII sanitization,
data capping, sequence deduplication, session lifecycle, and filtering.
"""

import json
import time
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from myrm_agent_harness.agent.event_log.backends.file_backend import (
    _DEFAULT_MAX_JSONL_LINE_BYTES,
    FileEventLogBackend,
)
from myrm_agent_harness.agent.event_log.logger import EventLogger, _cap_data_size
from myrm_agent_harness.agent.event_log.protocols import EventLogBackend
from myrm_agent_harness.agent.event_log.types import (
    EventFilter,
    SessionSummary,
    StructuredEvent,
    get_persistent_event_types,
)

# ============================================================================
# StructuredEvent
# ============================================================================


class TestStructuredEvent:
    def test_to_dict_roundtrip(self) -> None:
        event = StructuredEvent(
            sequence=1, timestamp=1700000000.123, event_type="tool_start", session_id="sess-1", data={"tool": "bash"}
        )
        d = event.to_dict()
        assert d["seq"] == 1
        assert d["ts"] == 1700000000.123
        assert d["type"] == "tool_start"
        assert d["sid"] == "sess-1"
        assert d["data"] == {"tool": "bash"}

    def test_frozen(self) -> None:
        event = StructuredEvent(sequence=1, timestamp=0.0, event_type="test", session_id="s", data={})
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            event.sequence = 2  # type: ignore[misc]


# ============================================================================
# SessionSummary
# ============================================================================


class TestSessionSummary:
    def test_defaults(self) -> None:
        s = SessionSummary()
        assert s.total_events == 0
        assert s.dropped_event_count == 0

    def test_to_dict_excludes_dropped_when_zero(self) -> None:
        s = SessionSummary()
        d = s.to_dict()
        assert "dropped_events" not in d

    def test_to_dict_includes_dropped_when_nonzero(self) -> None:
        s = SessionSummary(dropped_event_count=3)
        d = s.to_dict()
        assert d["dropped_events"] == 3


# ============================================================================
# EventFilter
# ============================================================================


class TestEventFilter:
    def test_defaults_are_none(self) -> None:
        f = EventFilter()
        assert f.event_types is None
        assert f.start_time is None
        assert f.limit is None


# ============================================================================
# get_persistent_event_types
# ============================================================================


class TestPersistentEventTypes:
    def test_returns_frozen_set(self) -> None:
        types = get_persistent_event_types()
        assert isinstance(types, frozenset)

    def test_excludes_streaming_types(self) -> None:
        types = get_persistent_event_types()
        assert "message" not in types
        assert "reasoning" not in types
        assert "ui_update" not in types

    def test_includes_persistent_types(self) -> None:
        types = get_persistent_event_types()
        assert "tool_start" in types
        assert "error" in types
        assert "status" in types

    def test_includes_takeover_trace(self) -> None:
        types = get_persistent_event_types()
        assert "takeover_trace" in types


# ============================================================================
# _cap_data_size
# ============================================================================


class TestCapDataSize:
    def test_small_data_unchanged(self) -> None:
        data = {"key": "small value"}
        assert _cap_data_size(data) is data

    def test_large_string_truncated(self) -> None:
        data = {"big": "x" * 10000}
        capped = _cap_data_size(data)
        assert len(capped["big"]) < 10000  # type: ignore[arg-type]
        assert "[truncated]" in str(capped["big"])

    def test_non_string_values_untouched(self) -> None:
        data = {"count": 42, "items": [1, 2, 3]}
        assert _cap_data_size(data) is data


# ============================================================================
# EventLogger
# ============================================================================


class TestEventLogger:
    @pytest.fixture
    def mock_backend(self) -> AsyncMock:
        backend = AsyncMock(spec=EventLogBackend)
        backend.append = AsyncMock()
        backend.close = AsyncMock()
        return backend

    @pytest.mark.asyncio
    async def test_start_emits_session_start(self, mock_backend: AsyncMock) -> None:
        el = EventLogger(mock_backend, "sess-test")
        await el.start()
        await el.close()

        calls = mock_backend.append.call_args_list
        all_events = [e for call in calls for e in call[0][0]]
        types = [e.event_type for e in all_events]
        assert "session_start" in types
        assert "session_end" in types

    @pytest.mark.asyncio
    async def test_log_filters_non_persistent(self, mock_backend: AsyncMock) -> None:
        el = EventLogger(mock_backend, "sess-test")
        await el.start()
        await el.log("message", {"text": "hello"})
        await el.close()

        calls = mock_backend.append.call_args_list
        all_events = [e for call in calls for e in call[0][0]]
        types = [e.event_type for e in all_events]
        assert "message" not in types

    @pytest.mark.asyncio
    async def test_log_persists_tool_start(self, mock_backend: AsyncMock) -> None:
        el = EventLogger(mock_backend, "sess-test")
        await el.start()
        await el.log("tool_start", {"tool": "bash"})
        await el.close()

        calls = mock_backend.append.call_args_list
        all_events = [e for call in calls for e in call[0][0]]
        types = [e.event_type for e in all_events]
        assert "tool_start" in types

    @pytest.mark.asyncio
    async def test_summary_counts_tool_calls(self, mock_backend: AsyncMock) -> None:
        el = EventLogger(mock_backend, "sess-test")
        await el.start()
        await el.log("tool_start", {"tool": "bash"})
        await el.log("tool_start", {"tool": "read"})
        await el.close()

        calls = mock_backend.append.call_args_list
        all_events = [e for call in calls for e in call[0][0]]
        end_events = [e for e in all_events if e.event_type == "session_end"]
        assert len(end_events) == 1
        summary = end_events[0].data["summary"]
        assert summary["tool_calls"] == 2

    @pytest.mark.asyncio
    async def test_close_is_idempotent(self, mock_backend: AsyncMock) -> None:
        el = EventLogger(mock_backend, "sess-test")
        await el.start()
        await el.close()
        await el.close()
        end_count = sum(
            1 for call in mock_backend.append.call_args_list for e in call[0][0] if e.event_type == "session_end"
        )
        assert end_count == 1

    @pytest.mark.asyncio
    async def test_log_after_close_is_noop(self, mock_backend: AsyncMock) -> None:
        el = EventLogger(mock_backend, "sess-test")
        await el.start()
        await el.close()
        await el.log("tool_start", {"tool": "bash"})

    @pytest.mark.asyncio
    async def test_sequence_monotonic(self, mock_backend: AsyncMock) -> None:
        el = EventLogger(mock_backend, "sess-test")
        await el.start()
        await el.log("tool_start", {"tool": "a"})
        await el.log("error", {"msg": "fail"})
        await el.close()

        calls = mock_backend.append.call_args_list
        all_events = [e for call in calls for e in call[0][0]]
        seqs = [e.sequence for e in all_events]
        assert seqs == sorted(seqs)
        assert len(set(seqs)) == len(seqs)

    @pytest.mark.asyncio
    async def test_compaction_counter(self, mock_backend: AsyncMock) -> None:
        el = EventLogger(mock_backend, "sess-test")
        await el.start()
        await el.log("status", {"kind": "compaction"})
        await el.close()

        calls = mock_backend.append.call_args_list
        all_events = [e for call in calls for e in call[0][0]]
        end_events = [e for e in all_events if e.event_type == "session_end"]
        summary = end_events[0].data["summary"]
        assert summary["compactions"] == 1

    @pytest.mark.asyncio
    async def test_failover_counter(self, mock_backend: AsyncMock) -> None:
        el = EventLogger(mock_backend, "sess-test")
        await el.start()
        await el.log("status", {"kind": "model_failover"})
        await el.close()

        calls = mock_backend.append.call_args_list
        all_events = [e for call in calls for e in call[0][0]]
        end_events = [e for e in all_events if e.event_type == "session_end"]
        summary = end_events[0].data["summary"]
        assert summary["failovers"] == 1


# ============================================================================
# FileEventLogBackend
# ============================================================================


class TestFileEventLogBackend:
    @pytest.fixture
    def log_dir(self, tmp_path: Path) -> Path:
        return tmp_path / "event_logs"

    @pytest.mark.asyncio
    async def test_append_creates_file(self, log_dir: Path) -> None:
        backend = FileEventLogBackend(log_dir, "sess-1")
        event = StructuredEvent(sequence=1, timestamp=time.time(), event_type="tool_start", session_id="sess-1", data={"t": "bash"})
        await backend.append([event])

        file_path = log_dir / "sess-1.jsonl"
        assert file_path.exists()
        lines = file_path.read_text().strip().splitlines()
        assert len(lines) == 1
        parsed = json.loads(lines[0])
        assert parsed["seq"] == 1
        assert parsed["type"] == "tool_start"

    @pytest.mark.asyncio
    async def test_sequence_deduplication(self, log_dir: Path) -> None:
        backend = FileEventLogBackend(log_dir, "sess-1")
        e1 = StructuredEvent(sequence=1, timestamp=time.time(), event_type="a", session_id="sess-1", data={})
        e2 = StructuredEvent(sequence=2, timestamp=time.time(), event_type="b", session_id="sess-1", data={})

        await backend.append([e1, e2])
        await backend.append([e1, e2])

        file_path = log_dir / "sess-1.jsonl"
        lines = file_path.read_text().strip().splitlines()
        assert len(lines) == 2

    @pytest.mark.asyncio
    async def test_get_events_basic(self, log_dir: Path) -> None:
        backend = FileEventLogBackend(log_dir, "sess-1")
        events = [StructuredEvent(sequence=i, timestamp=time.time(), event_type="tool_start", session_id="sess-1", data={"i": i}) for i in range(1, 4)]
        await backend.append(events)

        result = await backend.get_events("sess-1")
        assert len(result) == 3
        assert result[0].sequence == 1
        assert result[2].sequence == 3

    @pytest.mark.asyncio
    async def test_get_events_with_type_filter(self, log_dir: Path) -> None:
        backend = FileEventLogBackend(log_dir, "sess-1")
        await backend.append(
            [
                StructuredEvent(sequence=1, timestamp=time.time(), event_type="tool_start", session_id="sess-1", data={}),
                StructuredEvent(sequence=2, timestamp=time.time(), event_type="error", session_id="sess-1", data={}),
                StructuredEvent(sequence=3, timestamp=time.time(), event_type="tool_start", session_id="sess-1", data={}),
            ]
        )

        filt = EventFilter(event_types=frozenset(["error"]))
        result = await backend.get_events("sess-1", filt)
        assert len(result) == 1
        assert result[0].event_type == "error"

    @pytest.mark.asyncio
    async def test_get_events_with_limit(self, log_dir: Path) -> None:
        backend = FileEventLogBackend(log_dir, "sess-1")
        await backend.append([StructuredEvent(sequence=i, timestamp=time.time(), event_type="tool_start", session_id="sess-1", data={}) for i in range(1, 11)])

        filt = EventFilter(limit=3)
        result = await backend.get_events("sess-1", filt)
        assert len(result) == 3

    @pytest.mark.asyncio
    async def test_get_events_with_start_sequence(self, log_dir: Path) -> None:
        backend = FileEventLogBackend(log_dir, "sess-1")
        await backend.append([StructuredEvent(sequence=i, timestamp=time.time(), event_type="tool_start", session_id="sess-1", data={}) for i in range(1, 6)])

        filt = EventFilter(start_sequence=3)
        result = await backend.get_events("sess-1", filt)
        assert len(result) == 3
        assert result[0].sequence == 3

    @pytest.mark.asyncio
    async def test_get_events_empty_file(self, log_dir: Path) -> None:
        backend = FileEventLogBackend(log_dir, "sess-none")
        result = await backend.get_events("sess-none")
        assert result == []

    @pytest.mark.asyncio
    async def test_close_is_noop(self, log_dir: Path) -> None:
        backend = FileEventLogBackend(log_dir, "sess-1")
        await backend.close()

    @pytest.mark.asyncio
    async def test_protocol_compliance(self) -> None:
        assert isinstance(FileEventLogBackend(Path("/tmp"), "s"), EventLogBackend)

    @pytest.mark.asyncio
    async def test_append_downgrades_oversized_nested_payload(
        self, log_dir: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Nested list payload can exceed per-line cap without top-level long strings (see _cap_data_size)."""
        import logging

        caplog.set_level(logging.WARNING)
        small_limit = 4096
        backend = FileEventLogBackend(log_dir, "sess-big", max_jsonl_line_bytes=small_limit)
        huge: dict[str, object] = {"items": ["x" * 200] * 80}
        event = StructuredEvent(sequence=1, timestamp=time.time(), event_type="tool_start", session_id="sess-big", data=huge)
        await backend.append([event])

        file_path = log_dir / "sess-big.jsonl"
        raw = file_path.read_bytes()
        first_line = raw.split(b"\n", 1)[0] + b"\n"
        assert len(first_line) <= small_limit

        evs = await backend.get_events("sess-big")
        assert len(evs) == 1
        data = evs[0].data
        assert data.get("_jsonl_oversized") is True
        assert isinstance(data.get("_original_serialized_bytes"), int)
        assert int(data["_original_serialized_bytes"]) > small_limit

        assert "jsonl_line_downgraded" in caplog.text

    @pytest.mark.asyncio
    async def test_append_downgrades_nested_payload_over_default_100kb(self, log_dir: Path) -> None:
        """Default 100KB line cap: nested list (no single top-level 4K str) must still downgrade."""
        backend = FileEventLogBackend(log_dir, "sess-100k")
        items = ["y" * 100] * 1300
        event = StructuredEvent(sequence=1, timestamp=time.time(), event_type="error", session_id="sess-100k", data={"items": items})
        await backend.append([event])
        line = (log_dir / "sess-100k.jsonl").read_text().splitlines()[0]
        assert len(line.encode("utf-8")) <= _DEFAULT_MAX_JSONL_LINE_BYTES
        evs = await backend.get_events("sess-100k")
        assert evs[0].data.get("_jsonl_oversized") is True
        assert int(evs[0].data["_original_serialized_bytes"]) > _DEFAULT_MAX_JSONL_LINE_BYTES


# ============================================================================
# Integration: EventLogger + FileEventLogBackend
# ============================================================================


class TestEventLogIntegration:
    @pytest.mark.asyncio
    async def test_full_session_lifecycle(self, tmp_path: Path) -> None:
        log_dir = tmp_path / "logs"
        backend = FileEventLogBackend(log_dir, "integ-1")
        el = EventLogger(backend, "integ-1")

        await el.start()
        await el.log("tool_start", {"tool": "bash"})
        await el.log("tool_start", {"tool": "read"})
        await el.log("error", {"msg": "test error"})
        await el.log("message", {"text": "should be filtered"})
        await el.log("status", {"kind": "compaction"})
        await el.close()

        events = await backend.get_events("integ-1")
        types = [e.event_type for e in events]

        assert types[0] == "session_start"
        assert types[-1] == "session_end"
        assert "tool_start" in types
        assert "error" in types
        assert "status" in types
        assert "message" not in types

        end_event = events[-1]
        summary = end_event.data["summary"]
        assert summary["tool_calls"] == 2
        assert summary["errors"] == 1
        assert summary["compactions"] == 1
        assert summary["duration_ms"] >= 0
