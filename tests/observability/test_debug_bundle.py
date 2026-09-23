"""Tests for session debug bundle assembler and single-variable rerun."""

import pytest

from myrm_agent_harness.observability.audit_trail.collector import DualTrackAuditCollector
from myrm_agent_harness.observability.debug_bundle import (
    BundleCompleteness,
    RerunVerdict,
    assemble_debug_bundle,
    single_variable_rerun,
)


def _collector_with_secret() -> DualTrackAuditCollector:
    collector = DualTrackAuditCollector()
    collector.log_intent(
        session_id="s1",
        agent_id="a1",
        tool_name="search",
        intent_summary="lookup",
        proposed_args={"api_key": "sk-abcdefghijklmnop123456"},
    )
    return collector


def test_assemble_complete_bundle_redacts_secrets():
    bundle = assemble_debug_bundle(
        collector=_collector_with_secret(),
        session_id="s1",
        agent_id="a1",
        memory_trace={"hits": 2, "query": "key sk-abcdefghijklmnop123456"},
        failure_summary={"mode": "recall-miss"},
        config_snapshot={"model": "x"},
    )
    assert bundle.completeness == BundleCompleteness.COMPLETE
    assert bundle.missing_sections == []
    assert bundle.fingerprint != ""
    assert {section.name for section in bundle.sections} == {"audit", "memory_trace", "failure", "config"}
    dumped = str(bundle.sections)
    assert "sk-abcdefghijklmnop123456" not in dumped
    assert "[REDACTED" in dumped


def test_assemble_partial_bundle_lists_missing_sections():
    bundle = assemble_debug_bundle(collector=DualTrackAuditCollector(), session_id="s1", agent_id="a1")
    assert bundle.completeness == BundleCompleteness.PARTIAL
    assert bundle.missing_sections == ["memory_trace", "failure", "config"]


def test_assemble_truncates_oversized_payloads():
    bundle = assemble_debug_bundle(
        collector=DualTrackAuditCollector(),
        session_id="s1",
        agent_id="a1",
        memory_trace={"blob": "x" * 9000},
        failure_summary={"mode": "m"},
        config_snapshot={"model": "x"},
    )
    trace = next(section for section in bundle.sections if section.name == "memory_trace")
    assert trace.truncated is True
    assert bundle.completeness == BundleCompleteness.COMPLETE


def test_single_variable_rerun_unchanged_and_altered():
    base = {"model": "m1", "skill": "s1"}
    same = single_variable_rerun(
        session_id="s1",
        base_config=base,
        varied_key="skill",
        varied_value="s1",
        baseline_digest="d0",
        runner=lambda cfg: "d0",
    )
    assert same.verdict == RerunVerdict.UNCHANGED
    moved = single_variable_rerun(
        session_id="s1",
        base_config=base,
        varied_key="model",
        varied_value="m2",
        baseline_digest="d0",
        runner=lambda cfg: "d1",
    )
    assert moved.verdict == RerunVerdict.ALTERED
    assert moved.varied_key == "model"


def test_single_variable_rerun_rejects_unknown_key():
    with pytest.raises(ValueError, match="varied_key"):
        single_variable_rerun(
            session_id="s1",
            base_config={"model": "m1"},
            varied_key="nope",
            varied_value="x",
            baseline_digest="d0",
            runner=lambda cfg: "d0",
        )
