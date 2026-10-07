"""[POS]: tests/unit/toolkits/memory/test_context_ingestion_suite.py
[INPUT]: Synthetic multi-source transcripts (Plaud JSON, WebVTT, SRT, text).
[OUTPUT]: Comprehensive test suite verifying parser, deduplication, distiller, and gateway.
"""

import json
from pathlib import Path

import pytest

from myrm_agent_harness.toolkits.memory.ingestion_gateway import (
    ContextIngestionPayload,
    IngestionIdempotencyGuard,
    IngestionSourceType,
    TranscriptUniversalParser,
    UniversalContextIngestionGateway,
    VoiceContextDistiller,
    VoiceTranscriptSegment,
)


@pytest.fixture
def temp_db(tmp_path: Path) -> Path:
    return tmp_path / "test_ingestion_guard.db"


def test_plaud_json_parsing() -> None:
    parser = TranscriptUniversalParser()
    sample_data = {
        "transcription": [
            {
                "speaker": "Alice",
                "start_time": 0.5,
                "end_time": 3.2,
                "content": "Hello team, let's review the architecture roadmap.",
                "confidence": 0.98,
            },
            {
                "speaker": "Bob",
                "start_time": 3.5,
                "end_time": 6.8,
                "content": "Agreed. We decided to use SQLite for local caching.",
                "confidence": 0.95,
            },
        ]
    }
    payload = ContextIngestionPayload(
        source_type=IngestionSourceType.PLAUD_VOICE_CARD,
        device_id="plaud_note_01",
        title="Weekly Sync",
        raw_payload=json.dumps(sample_data),
    )
    segments = parser.parse(payload)
    assert len(segments) == 2
    assert segments[0].speaker == "Alice"
    assert segments[0].start_sec == 0.5
    assert segments[1].speaker == "Bob"
    assert "SQLite" in segments[1].text


def test_webvtt_and_srt_parsing() -> None:
    parser = TranscriptUniversalParser()

    # WebVTT
    vtt_content = """WEBVTT

00:01.000 --> 00:04.000
<v Charlie>Here is the action item for tomorrow.</v>

00:05.000 --> 00:08.000
<v Dave>I will do the PR review by next Monday.</v>
"""
    vtt_payload = ContextIngestionPayload(
        source_type=IngestionSourceType.WEBVTT,
        device_id="web_stream",
        title="Standup",
        raw_payload=vtt_content,
    )
    vtt_segments = parser.parse(vtt_payload)
    assert len(vtt_segments) == 2
    assert vtt_segments[0].speaker == "Charlie"
    assert "action item" in vtt_segments[0].text
    assert vtt_segments[1].speaker == "Dave"

    # SRT
    srt_content = """1
00:00:01,000 --> 00:00:03,500
Eve: We agreed to proceed with SQLite WAL mode.

2
00:00:04,000 --> 00:00:07,000
Frank: Frank will follow up on benchmark measurements.
"""
    srt_payload = ContextIngestionPayload(
        source_type=IngestionSourceType.SRT,
        device_id="desktop_mic",
        title="Tech Discussion",
        raw_payload=srt_content,
    )
    srt_segments = parser.parse(srt_payload)
    assert len(srt_segments) == 2
    assert srt_segments[0].speaker == "Eve"
    assert srt_segments[1].speaker == "Frank"


def test_speaker_merging_and_distillation() -> None:
    distiller = VoiceContextDistiller()
    raw_segments = [
        VoiceTranscriptSegment(speaker="Alice", start_sec=0.0, end_sec=2.0, text="First statement."),
        VoiceTranscriptSegment(speaker="Alice", start_sec=2.0, end_sec=5.0, text="Second continuation."),
        VoiceTranscriptSegment(speaker="Bob", start_sec=5.0, end_sec=8.0, text="We decided on Rust."),
        VoiceTranscriptSegment(speaker="Bob", start_sec=8.0, end_sec=11.0, text="Alice will do tests."),
    ]

    merged = distiller.merge_adjacent_segments(raw_segments)
    assert len(merged) == 2
    assert merged[0].speaker == "Alice"
    assert merged[0].text == "First statement. Second continuation."
    assert merged[0].start_sec == 0.0
    assert merged[0].end_sec == 5.0

    decisions = distiller.extract_decisions(merged)
    assert len(decisions) == 1
    assert "decided" in decisions[0]

    actions = distiller.extract_action_items(merged)
    assert len(actions) == 1
    assert "will do" in actions[0]

    summary = distiller.build_summary("Architecture Sync", merged, ["Alice", "Bob"])
    assert "Title: Architecture Sync" in summary
    assert "Alice" in summary
    assert "Bob" in summary


def test_idempotency_deduplication(temp_db: Path) -> None:
    guard = IngestionIdempotencyGuard(db_path=temp_db)
    fp = guard.compute_fingerprint("Unique text recording content", device_id="dev_123")

    assert not guard.is_recorded(fp)
    recorded = guard.record_fingerprint(fp, "raw_transcript", "dev_123", "Demo 1")
    assert recorded is True
    assert guard.is_recorded(fp)

    # Duplicate insertion fails gracefully
    dup_recorded = guard.record_fingerprint(fp, "raw_transcript", "dev_123", "Demo 1")
    assert dup_recorded is False

    records = guard.list_records()
    assert len(records) == 1
    assert records[0]["fingerprint"] == fp


def test_gateway_end_to_end_flow(temp_db: Path) -> None:
    gateway = UniversalContextIngestionGateway(db_path=temp_db)

    raw_text = """Alice: 确定使用方案A作为持久化底座。
Alice: 另外请注意下周完成基准测试验证。
Bob: 收到，我来负责整理压力测试脚本。
"""
    payload = ContextIngestionPayload(
        source_type=IngestionSourceType.RAW_TRANSCRIPT,
        device_id="hardware_card_001",
        title="项目技术评审会",
        raw_payload=raw_text,
    )

    # First Ingestion
    res1 = gateway.ingest(payload)
    assert not res1.is_duplicate
    assert res1.title == "项目技术评审会"
    assert res1.speaker_count == 2
    assert len(res1.decisions) >= 1
    assert any("确定" in d for d in res1.decisions)
    assert len(res1.action_items) >= 1
    assert any("负责" in a or "完成" in a for a in res1.action_items)

    # Second Ingestion (Exact duplicate)
    res2 = gateway.ingest(payload)
    assert res2.is_duplicate
    assert res2.fingerprint == res1.fingerprint
    assert "Skipped duplicate" in res2.summary

    # History query
    history = gateway.list_history()
    assert len(history) == 1
    assert history[0]["title"] == "项目技术评审会"
