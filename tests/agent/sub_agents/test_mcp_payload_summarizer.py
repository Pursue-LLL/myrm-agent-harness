"""Unit tests for Heavy MCP Payload Summarizer & Contamination Doctor (Item 44).

[INPUT]
- HeavyMcpPayloadSummarizer, McpContaminationDoctor, domain types.

[OUTPUT]
- Pytest cases verifying payload threshold detection, structured summary compression,
  token savings ratio, and contamination audit risk levels.

[POS]
- myrm-agent-harness/tests/agent/sub_agents/test_mcp_payload_summarizer.py
"""

from __future__ import annotations

import json

import pytest

from myrm_agent_harness.agent.sub_agents.mcp_summarizer import (
    ContaminationRiskLevel,
    HeavyMcpPayloadSummarizer,
    McpContaminationDoctor,
    McpSummarizerError,
    PayloadExtractionTarget,
    SubagentPresetSpec,
)


def test_is_heavy_payload_thresholds() -> None:
    summarizer = HeavyMcpPayloadSummarizer()
    small_payload = "hello world"
    assert summarizer.is_heavy_payload(small_payload) is False

    large_payload = "x" * 5000
    assert summarizer.is_heavy_payload(large_payload) is True


def test_summarize_dict_payload_token_savings() -> None:
    summarizer = HeavyMcpPayloadSummarizer()

    # Create bulky payload simulating Figma or Notion export
    large_list = [{"id": i, "name": f"item_{i}", "metadata": "extra_data_" * 20} for i in range(100)]
    bulky_data = {
        "title": "Figma Canvas Document Export",
        "version": "1.4.0",
        "nodes": large_list,
        "design_tokens": {"primary": "#ff0000", "secondary": "#00ff00"},
        "comments": ["comment_" + str(i) for i in range(50)],
    }
    raw_json = json.dumps(bulky_data, ensure_ascii=False)
    assert len(raw_json) > 10000

    target = PayloadExtractionTarget(
        required_keys=("title", "nodes", "design_tokens"),
        max_summary_tokens=500,
        summarize_nested_lists_limit=3,
    )
    artifact = summarizer.summarize_payload(
        source_tool="figma_mcp_export",
        raw_payload=raw_json,
        target=target,
        artifact_store_path="/tmp/figma_dump.json",
    )

    assert artifact.source_tool_or_mcp == "figma_mcp_export"
    assert artifact.file_reference_path == "/tmp/figma_dump.json"
    assert "Figma Canvas Document Export" in artifact.summary_text
    assert artifact.raw_payload_bytes > 10000
    assert artifact.summary_bytes < 1500
    # Expected significant token/byte savings (> 38%)
    assert artifact.token_saving_ratio >= 0.38
    assert "title" in artifact.extracted_fields
    assert "nodes" in artifact.extracted_fields


def test_summarize_plain_text_payload() -> None:
    summarizer = HeavyMcpPayloadSummarizer()
    raw_text = "Detailed documentation log chunk:\n" + ("Log line message detail\n" * 200)

    artifact = summarizer.summarize_payload(
        source_tool="server_log_fetcher",
        raw_payload=raw_text,
    )

    assert artifact.source_tool_or_mcp == "server_log_fetcher"
    assert artifact.raw_payload_bytes > 4000
    assert artifact.token_saving_ratio > 0.0
    assert "Log line message detail" in artifact.summary_text


def test_contamination_doctor_diagnostics() -> None:
    doctor = McpContaminationDoctor()

    # 1. Properly isolated via subagent is always SAFE
    isolated_report = doctor.diagnose_payload(
        raw_payload="x" * 50000,
        is_isolated_via_subagent=True,
    )
    assert isolated_report.risk_level == ContaminationRiskLevel.SAFE
    assert isolated_report.is_isolated_via_subagent is True

    # 2. Small payload in main chat is SAFE
    small_report = doctor.diagnose_payload(
        raw_payload="small summary string",
        is_isolated_via_subagent=False,
    )
    assert small_report.risk_level == ContaminationRiskLevel.SAFE

    # 3. Bulky payload (8KB) without isolation is SUSPICIOUS
    mid_report = doctor.diagnose_payload(
        raw_payload="x" * 8000,
        is_isolated_via_subagent=False,
    )
    assert mid_report.risk_level == ContaminationRiskLevel.SUSPICIOUS
    assert "mcp-data-summarizer" in mid_report.remediation_advice

    # 4. Enormous payload (30KB) without isolation is SEVERE_CONTAMINATION
    severe_report = doctor.diagnose_payload(
        raw_payload="x" * 30000,
        is_isolated_via_subagent=False,
    )
    assert severe_report.risk_level == ContaminationRiskLevel.SEVERE_CONTAMINATION
    assert "Severe Contamination Risk" in severe_report.remediation_advice


def test_invalid_input_error_handling() -> None:
    summarizer = HeavyMcpPayloadSummarizer()
    with pytest.raises(McpSummarizerError, match="cannot be empty"):
        summarizer.summarize_payload(source_tool="   ", raw_payload="{}")


def test_subagent_preset_spec() -> None:
    spec = SubagentPresetSpec()
    assert spec.name == "mcp-data-summarizer"
    assert "read_file" in spec.tools_whitelist
    assert spec.default_extraction_target.max_summary_tokens == 800
