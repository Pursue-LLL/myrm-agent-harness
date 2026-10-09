"""Comprehensive tests for CorruptSessionStorageGracefulDegradationAndAutoHealingSuite.

[INPUT]
- corrupt_session_healing package contracts and implementations.

[OUTPUT]
- Deterministic verification of corrupt record sandboxing, partial transcript salvaging,
  zero-freeze fresh session healing, and master facade degradation.

[POS]
- Sub-package: tests.agent.context_management
- Module: test_corrupt_session_healing_suite.py
"""

from pathlib import Path

import pytest

from myrm_agent_harness.agent.context_management.corrupt_session_healing import (
    CorruptRecordSandbox,
    CorruptSessionStorageGracefulDegradationAndAutoHealingSuite,
    FreshSessionAutoHealer,
    HealingSuiteConfig,
    PartialTranscriptSalvager,
    RestorationOutcome,
    RestorationStatus,
    SalvagedMessageItem,
)


def test_corrupt_record_sandbox_archive(tmp_path: Path) -> None:
    """Verifies that corrupted session payloads are safely quarantined with SHA-256 and diagnostics."""
    archive_dir = tmp_path / "sandbox_archive"
    config = HealingSuiteConfig(archive_directory=str(archive_dir))
    sandbox = CorruptRecordSandbox(config=config)

    raw_corrupt = '{"session_id": "001", "messages": [{"role": "user", "content": "test"}, broken...'
    archive = sandbox.quarantine_payload(
        session_id="session_001",
        raw_payload=raw_corrupt,
        error_diagnostic="JSONDecodeError: Unterminated string",
        salvaged_count=1,
    )

    # 1. Archive metadata verified
    assert archive.corrupted_session_id == "session_001"
    assert archive.salvaged_message_count == 1
    assert archive.error_diagnostic == "JSONDecodeError: Unterminated string"
    assert len(archive.content_hash) == 64

    # 2. Archive file physically created on disk in quarantine dir
    archived_file = Path(archive.archive_path)
    assert archived_file.exists()
    assert archived_file.parent == archive_dir

    # 3. Lookup via sandbox memory index
    cached = sandbox.get_archive("session_001")
    assert cached is not None
    assert cached.content_hash == archive.content_hash
    assert len(sandbox.list_archives()) == 1


def test_partial_transcript_salvager_jsonl_and_json() -> None:
    """Verifies best-effort message salvage across JSON arrays, JSONL streams, and broken blocks."""
    config = HealingSuiteConfig(max_salvaged_messages=10)
    salvager = PartialTranscriptSalvager(config=config)

    # Case 1: Valid clean JSON array
    clean_json = (
        '[\n'
        '  {"role": "system", "content": "System prompt"},\n'
        '  {"role": "user", "content": "Hello"}\n'
        ']'
    )
    salvaged_clean = salvager.salvage(clean_json)
    assert len(salvaged_clean) == 2
    assert salvaged_clean[0].role == "system"
    assert salvaged_clean[1].role == "user"

    # Case 2: JSONL stream with a broken middle line
    jsonl_content = (
        '{"role": "user", "content": "Hello agent"}\n'
        '{"role": "assistant", "content": "Hello! How can I assist you today?"}\n'
        'BROKEN_GARBAGE_JSON_LINE\n'
        '{"role": "user", "content": "Inspect repository"}\n'
    )
    salvaged_jsonl = salvager.salvage(jsonl_content)
    assert len(salvaged_jsonl) == 3
    assert salvaged_jsonl[0].content == "Hello agent"
    assert salvaged_jsonl[1].content == "Hello! How can I assist you today?"
    assert salvaged_jsonl[2].content == "Inspect repository"

    # Case 3: Truncated JSON array recovered via regex salvage
    truncated_json = (
        '[\n'
        '  {"role": "user", "content": "Task 1"},\n'
        '  {"role": "assistant", "content": "Task 1 complete"},\n'
        '  {"role": "user", "content": "Task 2"'  # Truncated without close
    )
    salvaged_regex = salvager.salvage(truncated_json)
    assert len(salvaged_regex) == 2
    assert salvaged_regex[0].content == "Task 1"
    assert salvaged_regex[1].content == "Task 1 complete"

    # Case 4: Completely empty string
    empty_salvaged = salvager.salvage("   \n\t ")
    assert empty_salvaged == tuple()


def test_fresh_session_auto_healer_derivation_and_intro() -> None:
    """Verifies that fresh session derivation produces resilient context and prevents UI freezes."""
    config = HealingSuiteConfig(fresh_session_prefix="test-healed")
    healer = FreshSessionAutoHealer(config=config)

    salvaged = (
        SalvagedMessageItem(message_id="msg-1", role="user", content="Deploy v1.0", salvaged_index=0),
        SalvagedMessageItem(message_id="msg-2", role="assistant", content="Deploying", salvaged_index=1),
    )

    # 1. Healed with salvaged messages
    outcome_partial = healer.derive_healed_session(
        corrupted_session_id="corrupt-sess-xyz",
        salvaged_messages=salvaged,
        diagnostic_reason="Invalid token at pos 42",
    )
    assert outcome_partial.status == RestorationStatus.SALVAGED_PARTIAL
    assert outcome_partial.original_session_id == "corrupt-sess-xyz"
    assert outcome_partial.active_session_id.startswith("test-healed-corrupt-sess")
    assert outcome_partial.is_fresh_session is True
    assert len(outcome_partial.salvaged_messages) == 2

    intro_partial = healer.render_healed_context_intro(outcome_partial)
    assert "[SESSION_AUTO_HEALED_NOTICE]" in intro_partial
    assert "corrupt-sess-xyz" in intro_partial
    assert "2 messages successfully recovered" in intro_partial

    # 2. Healed without any salvaged messages (clean fallback)
    outcome_empty = healer.derive_healed_session(
        corrupted_session_id="corrupt-empty-abc",
        salvaged_messages=tuple(),
        diagnostic_reason="File completely erased",
    )
    assert outcome_empty.status == RestorationStatus.HEALED_FRESH_FALLBACK
    assert outcome_empty.is_fresh_session is True
    intro_empty = healer.render_healed_context_intro(outcome_empty)
    assert "Salvaged History: None (Fresh start)" in intro_empty


def test_corrupt_session_healing_suite_clean_flow(tmp_path: Path) -> None:
    """Verifies that intact sessions restore cleanly without invoking quarantine or fresh derivation."""
    archive_dir = tmp_path / "sandbox_archive"
    config = HealingSuiteConfig(archive_directory=str(archive_dir))
    suite = CorruptSessionStorageGracefulDegradationAndAutoHealingSuite(config=config)

    clean_payload = (
        '[\n'
        '  {"role": "user", "content": "Calculate 2+2"},\n'
        '  {"role": "assistant", "content": "4"}\n'
        ']'
    )

    outcome = suite.restore_session_safe(
        session_id="clean-session-001",
        raw_payload=clean_payload,
    )

    assert outcome.status == RestorationStatus.RESTORED_CLEAN
    assert outcome.original_session_id == "clean-session-001"
    assert outcome.active_session_id == "clean-session-001"
    assert outcome.is_fresh_session is False
    assert len(outcome.salvaged_messages) == 2
    assert suite.get_quarantine_archive("clean-session-001") is None


def test_corrupt_session_healing_suite_corrupted_salvage_flow(tmp_path: Path) -> None:
    """Verifies full auto-healing degradation flow: quarantine + salvage + fresh session migration."""
    archive_dir = tmp_path / "sandbox_archive"
    config = HealingSuiteConfig(archive_directory=str(archive_dir))
    suite = CorruptSessionStorageGracefulDegradationAndAutoHealingSuite(config=config)

    corrupted_payload = (
        '[\n'
        '  {"role": "user", "content": "Start cluster"},\n'
        '  {"role": "assistant", "content": "Cluster starting"},\n'
        '  SYNTAX_ERROR_CRASH_CORRUPTED_LINE'
    )

    outcome = suite.restore_session_safe(
        session_id="sess-broken-888",
        raw_payload=corrupted_payload,
        deserializer_error="Unexpected token in JSON",
    )

    # 1. Degradation and healing activated
    assert outcome.status == RestorationStatus.SALVAGED_PARTIAL
    assert outcome.is_fresh_session is True
    assert outcome.original_session_id == "sess-broken-888"
    assert outcome.active_session_id.startswith("fresh-healed-sess-broken-")
    assert len(outcome.salvaged_messages) == 2

    # 2. Archive registered in sandbox
    archive = suite.get_quarantine_archive("sess-broken-888")
    assert archive is not None
    assert archive.salvaged_message_count == 2
    assert Path(archive.archive_path).exists()
    assert len(suite.list_quarantined_archives()) == 1

    # 3. Intro notice rendered properly
    intro = suite.render_restoration_intro(outcome)
    assert "[SESSION_AUTO_HEALED_NOTICE]" in intro
    assert "sess-broken-888" in intro


def test_corrupt_session_healing_suite_total_corruption_fresh_reset(tmp_path: Path) -> None:
    """Verifies that completely unrecoverable files avoid white screens by fresh reset fallback."""
    archive_dir = tmp_path / "sandbox_archive"
    config = HealingSuiteConfig(archive_directory=str(archive_dir))
    suite = CorruptSessionStorageGracefulDegradationAndAutoHealingSuite(config=config)

    unrecoverable_raw = "@@@BINARY_GARBAGE_UNPARSEABLE_DUMP@@@"

    outcome = suite.restore_session_safe(
        session_id="sess-dead-999",
        raw_payload=unrecoverable_raw,
    )

    assert outcome.status == RestorationStatus.HEALED_FRESH_FALLBACK
    assert outcome.is_fresh_session is True
    assert len(outcome.salvaged_messages) == 0

    archive = suite.get_quarantine_archive("sess-dead-999")
    assert archive is not None
    assert archive.salvaged_message_count == 0
