"""Unit tests for IPC Message Clamping and Large Artifact Spillover Suite (Item 216).

[INPUT]
- IpcMessageClampingAndSpilloverEngine, IpcClampingConfig, IpcClampingAction.
- Simulated inter-agent communications with varying payload lengths.

[OUTPUT]
- Deterministic verification of message clamping, automated artifact spillover,
- summary preview generation, and on-demand file payload retrieval.

[POS]
- Verifies that oversized inter-agent messages are safely offloaded to artifacts,
- preventing downstream agent context window explosion.
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.context_management.ipc_clamping import (
    IpcClampingAction,
    IpcClampingConfig,
    IpcMessageClampingAndSpilloverEngine,
)


def test_standard_message_passthrough() -> None:
    """Verifies that normal-sized IPC messages pass through without clamping or rewriting."""
    engine = IpcMessageClampingAndSpilloverEngine(
        config=IpcClampingConfig(max_clamped_chars=1000)
    )
    sender = "researcher_agent_01"
    receiver = "analyst_agent_02"
    msg = "Here is the concise summary: Q3 revenue is up 12% YoY with gross margins steady."

    outcome = engine.process_inter_agent_message(sender, receiver, msg)
    assert outcome.action == IpcClampingAction.PASSTHROUGH
    assert outcome.effective_message == msg
    assert outcome.original_char_count == len(msg)
    assert outcome.effective_char_count == len(msg)
    assert outcome.spillover_artifact is None
    assert outcome.duration_ms >= 0.0


def test_large_message_automated_spillover_and_retrieval() -> None:
    """Verifies that oversized messages are offloaded to sandbox artifacts and rewritten cleanly."""
    engine = IpcMessageClampingAndSpilloverEngine(
        config=IpcClampingConfig(
            max_clamped_chars=200,
            summary_preview_chars=60,
            artifact_storage_prefix="/workspace/artifacts/spillover",
        )
    )
    sender = "crawler_bot"
    receiver = "coder_agent"

    # Simulated huge text payload (8000+ chars)
    raw_huge_text = "Headline: Major Tech Release Notes.\n" + ("Log line trace entry data sample.\n" * 250)
    assert len(raw_huge_text) > 200

    outcome = engine.process_inter_agent_message(sender, receiver, raw_huge_text)
    assert outcome.action == IpcClampingAction.SPILLOVER_REPLACED
    assert outcome.spillover_artifact is not None
    assert outcome.original_char_count == len(raw_huge_text)
    assert outcome.effective_char_count < len(raw_huge_text)

    artifact = outcome.spillover_artifact
    assert artifact.sender_agent_id == sender
    assert artifact.receiver_agent_id == receiver
    assert artifact.artifact_path.startswith("/workspace/artifacts/spillover/spill_")
    assert len(artifact.sha256) == 64
    assert artifact.original_char_count == len(raw_huge_text)

    # Check rewritten effective message structure
    eff_msg = outcome.effective_message
    assert "[LARGE IPC PAYLOAD DETECTED & SPILLED:" in eff_msg
    assert "Content Digest (SHA-256):" in eff_msg
    assert "file://" + artifact.artifact_path in eff_msg
    assert "Use 'read_file' tool" in eff_msg

    # Verify lossless retrieval of offloaded payload from engine
    recovered_by_id = engine.get_spillover_payload(artifact.artifact_id)
    assert recovered_by_id == raw_huge_text

    recovered_by_path = engine.get_spillover_payload(artifact.artifact_path)
    assert recovered_by_path == raw_huge_text

    # Verify metadata spec retrieval
    spec = engine.get_artifact_spec(artifact.artifact_id)
    assert spec is not None
    assert spec.sha256 == artifact.sha256


def test_oversize_rejection_when_spillover_disabled() -> None:
    """Verifies that oversized messages are rejected when auto_spillover is disabled."""
    engine = IpcMessageClampingAndSpilloverEngine(
        config=IpcClampingConfig(max_clamped_chars=100, auto_spillover=False)
    )
    sender = "scanner_agent"
    receiver = "report_agent"
    large_msg = "X" * 150

    outcome = engine.process_inter_agent_message(sender, receiver, large_msg)
    assert outcome.action == IpcClampingAction.REJECTED_OVERSIZE
    assert outcome.spillover_artifact is None
    assert "[IPC ERROR:" in outcome.effective_message
    assert "exceeds clamping limit 100" in outcome.effective_message


def test_clear_and_non_existent_artifacts() -> None:
    """Verifies clearing stored artifacts and query for non-existent items."""
    engine = IpcMessageClampingAndSpilloverEngine(config=IpcClampingConfig(max_clamped_chars=50))
    huge_msg = "Data " * 30
    outcome = engine.process_inter_agent_message("a1", "a2", huge_msg)
    assert outcome.spillover_artifact is not None

    art_id = outcome.spillover_artifact.artifact_id
    assert engine.get_spillover_payload(art_id) is not None

    engine.clear()
    assert engine.get_spillover_payload(art_id) is None
    assert engine.get_artifact_spec(art_id) is None
    assert engine.get_spillover_payload("non_existent") is None
