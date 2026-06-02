"""Tests for llm_auditor.py — LLM audit with only-escalate merge."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from unittest.mock import AsyncMock

import pytest

from myrm_agent_harness.backends.skills.scanning.llm_auditor import (
    SkillLLMAuditor,
    _parse_llm_response,
)
from myrm_agent_harness.backends.skills.scanning.scanner import (
    ScanFinding,
    ScanResult,
    ScanSeverity,
)


@dataclass
class MockMessage:
    content: str


class TestParseLlmResponse:
    """Tests for _parse_llm_response."""

    def test_empty_findings(self):
        assert _parse_llm_response('{"findings": []}') == []

    def test_single_finding(self):
        resp = '{"findings": [{"description": "data exfil via curl", "severity": "high"}]}'
        findings = _parse_llm_response(resp)
        assert len(findings) == 1
        assert findings[0].severity == ScanSeverity.HIGH
        assert "data exfil" in findings[0].description
        assert findings[0].threat_type == "llm_audit"

    def test_multiple_findings(self):
        resp = '{"findings": [{"description": "a", "severity": "critical"}, {"description": "b", "severity": "low"}]}'
        findings = _parse_llm_response(resp)
        assert len(findings) == 2
        assert findings[0].severity == ScanSeverity.CRITICAL
        assert findings[1].severity == ScanSeverity.LOW

    def test_markdown_wrapped_json(self):
        resp = '```json\n{"findings": [{"description": "test", "severity": "medium"}]}\n```'
        findings = _parse_llm_response(resp)
        assert len(findings) == 1
        assert findings[0].severity == ScanSeverity.MEDIUM

    def test_invalid_json_returns_empty(self):
        assert _parse_llm_response("not json at all") == []

    def test_non_dict_returns_empty(self):
        assert _parse_llm_response("[1, 2, 3]") == []

    def test_missing_description_skipped(self):
        resp = '{"findings": [{"severity": "high"}]}'
        findings = _parse_llm_response(resp)
        assert len(findings) == 0

    def test_unknown_severity_defaults_medium(self):
        resp = '{"findings": [{"description": "test", "severity": "extreme"}]}'
        findings = _parse_llm_response(resp)
        assert len(findings) == 1
        assert findings[0].severity == ScanSeverity.MEDIUM

    def test_non_dict_items_skipped(self):
        resp = '{"findings": ["not a dict", {"description": "valid", "severity": "low"}]}'
        findings = _parse_llm_response(resp)
        assert len(findings) == 1


class TestSkillLLMAuditor:
    """Tests for SkillLLMAuditor.audit."""

    @pytest.fixture()
    def mock_llm(self):
        llm = AsyncMock()
        llm.ainvoke = AsyncMock(
            return_value=MockMessage(content='{"findings": [{"description": "subtle exfil", "severity": "high"}]}')
        )
        return llm

    @pytest.mark.asyncio
    async def test_merges_llm_findings(self, mock_llm):
        auditor = SkillLLMAuditor(mock_llm)
        static = ScanResult(
            skill_name="test",
            findings=[ScanFinding("static", ScanSeverity.LOW, "minor")],
        )
        result = await auditor.audit("test", "content", static)
        assert len(result.findings) == 2
        assert result.findings[0].threat_type == "static"
        assert result.findings[1].threat_type == "llm_audit"

    @pytest.mark.asyncio
    async def test_skips_when_already_reject(self, mock_llm):
        auditor = SkillLLMAuditor(mock_llm)
        static = ScanResult(
            skill_name="test",
            findings=[ScanFinding("critical", ScanSeverity.CRITICAL, "critical threat")],
        )
        result = await auditor.audit("test", "content", static)
        assert result is static
        mock_llm.ainvoke.assert_not_called()

    @pytest.mark.asyncio
    async def test_falls_back_on_timeout(self):
        llm = AsyncMock()

        async def slow_invoke(*args, **kwargs):
            await asyncio.sleep(100)

        llm.ainvoke = slow_invoke
        auditor = SkillLLMAuditor(llm)
        auditor._AUDIT_TIMEOUT_SECONDS = 0.01  # type: ignore[attr-defined]

        static = ScanResult(skill_name="test")

        import myrm_agent_harness.backends.skills.scanning.llm_auditor as mod

        original = mod._AUDIT_TIMEOUT_SECONDS
        mod._AUDIT_TIMEOUT_SECONDS = 0.01
        try:
            result = await auditor.audit("test", "content", static)
            assert result is static
        finally:
            mod._AUDIT_TIMEOUT_SECONDS = original

    @pytest.mark.asyncio
    async def test_falls_back_on_exception(self):
        llm = AsyncMock()
        llm.ainvoke = AsyncMock(side_effect=RuntimeError("LLM unavailable"))
        auditor = SkillLLMAuditor(llm)
        static = ScanResult(skill_name="test")
        result = await auditor.audit("test", "content", static)
        assert result is static

    @pytest.mark.asyncio
    async def test_empty_llm_findings_returns_static(self, mock_llm):
        mock_llm.ainvoke = AsyncMock(return_value=MockMessage(content='{"findings": []}'))
        auditor = SkillLLMAuditor(mock_llm)
        static = ScanResult(skill_name="test")
        result = await auditor.audit("test", "content", static)
        assert result is static

    @pytest.mark.asyncio
    async def test_truncates_long_content(self, mock_llm):
        auditor = SkillLLMAuditor(mock_llm)
        static = ScanResult(skill_name="test")
        long_content = "x" * 20000
        await auditor.audit("test", long_content, static)
        call_args = mock_llm.ainvoke.call_args[0][0]
        prompt_text = call_args[0].content
        assert "[... truncated for analysis ...]" in prompt_text
