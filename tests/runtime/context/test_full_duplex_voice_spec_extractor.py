"""Unit tests for full-duplex voice requirement discovery and structured spec extraction.

Verifies:
1. Turn recording with barge-in interruption detection and consultant phase state transitions.
2. Alignment consensus detection upon spoken approval phrases.
3. Distillation of multi-turn spoken dialogue into formal StructuredPlanSpec artifacts.
4. Automatic generation of module boundaries, explicit non-goals, and Kanban tasks.
5. Markdown spec artifact formatting with Mermaid flow diagrams.
6. Validation guard rejecting premature extraction with insufficient dialogue turns.
"""

from __future__ import annotations

from myrm_agent_harness.runtime.context.voice_spec_extractor_types import (
    VoiceConsultantPhase,
)
from myrm_agent_harness.runtime.context.voice_transcript_buffer import (
    VoiceTranscriptBuffer,
)
from myrm_agent_harness.runtime.context.voice_transcript_to_spec_extractor import (
    VoiceTranscriptToSpecExtractor,
)


def test_voice_transcript_buffer_turn_recording_and_phase_transitions() -> None:
    buffer = VoiceTranscriptBuffer()
    assert buffer.current_phase == VoiceConsultantPhase.EXPLORATION

    # Turn 1: User initial idea
    buffer.record_turn("user", "I want to build a cache middleware.")
    assert buffer.turn_count() == 1
    assert buffer.current_phase == VoiceConsultantPhase.EXPLORATION

    # Turn 2: Agent prompt
    buffer.record_turn("agent", "What backing store do you prefer? In-memory or persistent?")
    assert buffer.turn_count() == 2

    # Turn 3: User answers
    buffer.record_turn("user", "We should use persistent SQLite.")
    assert buffer.current_phase == VoiceConsultantPhase.DEEP_DIVE

    # Turn 4: User barge-in interruption
    buffer.record_turn("user", "Wait, also ensure zero backward compatibility debt.", is_interruption=True)
    turns = buffer.get_turns()
    assert len(turns) == 4
    assert turns[3].is_interruption

    # Verify transcript formatting
    raw = buffer.export_raw_transcript()
    assert "[USER]: I want to build a cache middleware." in raw
    assert "[USER] (INTERRUPTION): Wait, also ensure zero backward compatibility debt." in raw

    # Turn 5 & 6: Move into trade-off analysis
    buffer.record_turn("agent", "Understood. That simplifies the schema.")
    buffer.record_turn("agent", "Shall we finalize with SQLite WAL mode?")
    assert buffer.current_phase == VoiceConsultantPhase.TRADE_OFF_ANALYSIS

    # Final Turn: User gives alignment phrase
    buffer.record_turn("user", "赞同，开始执行！")
    assert buffer.detect_alignment_signal()
    assert buffer.current_phase == VoiceConsultantPhase.FINAL_ALIGNMENT


def test_voice_spec_extractor_generates_rigorous_plan_spec() -> None:
    buffer = VoiceTranscriptBuffer()
    extractor = VoiceTranscriptToSpecExtractor()

    # Build rich conversational requirement transcript
    buffer.record_turn("user", "I want an autonomous test runner that watches files.")
    buffer.record_turn("agent", "Great. Should we use DuckDB for storing run history?")
    buffer.record_turn("user", "Yes, DuckDB is great. But skip complex cloud telemetry, keep it single sandbox.")
    buffer.record_turn("agent", "Noted: DuckDB for analytics, no cloud telemetry, clean single-host.")
    buffer.record_turn("user", "就按这个方案做吧！")

    res = extractor.extract_plan_spec(buffer, project_title="Autonomous Watcher Engine")
    assert res.success
    assert res.spec is not None

    spec = res.spec
    assert spec.project_title == "Autonomous Watcher Engine"
    assert spec.source_turn_count == 5
    assert len(spec.core_modules) >= 3

    # Check extracted module details
    module_names = [m.module_name for m in spec.core_modules]
    assert "ExecutionCore" in module_names
    assert "StatePersistence" in module_names
    assert "TransportAndVisualUI" in module_names

    # Check persistence module picked up DuckDB tech from user text
    persistence_mod = next(m for m in spec.core_modules if m.module_name == "StatePersistence")
    assert any("DuckDB" in tech for tech in persistence_mod.technical_stack)

    # Check non-goals
    assert len(spec.explicit_non_goals) >= 2
    assert any("single-machine" in ng for ng in spec.explicit_non_goals)

    # Check Kanban tasks
    assert len(spec.kanban_tasks) >= 4
    assert any("Task 1:" in task for task in spec.kanban_tasks)

    # Verify buffer phase updated
    assert buffer.current_phase == VoiceConsultantPhase.SPEC_GENERATED


def test_format_markdown_artifact_renders_mermaid_and_sections() -> None:
    buffer = VoiceTranscriptBuffer()
    extractor = VoiceTranscriptToSpecExtractor()

    buffer.record_turn("user", "Build a minimal logging server.")
    buffer.record_turn("user", "赞同，开始执行")

    res = extractor.extract_plan_spec(buffer, project_title="Log Hub")
    assert res.success
    assert res.spec is not None

    markdown = extractor.format_markdown_artifact(res.spec)
    assert "# Technical Specification: Log Hub" in markdown
    assert "## 1. Executive Summary" in markdown
    assert "## 2. Core Modules Architecture" in markdown
    assert "```mermaid" in markdown
    assert "## 4. Explicit Non-Goals" in markdown
    assert "## 5. Kanban Task Breakdown" in markdown


def test_insufficient_turns_validation_guard() -> None:
    buffer = VoiceTranscriptBuffer()
    extractor = VoiceTranscriptToSpecExtractor()

    # Only 1 turn
    buffer.record_turn("user", "Hello.")
    res = extractor.extract_plan_spec(buffer)

    assert not res.success
    assert res.spec is None
    assert len(res.validation_errors) == 1
    assert "Insufficient dialogue turns" in res.validation_errors[0]
