"""Unit tests for Skill Security Scoring Gate and Preflight Protection."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from myrm_agent_harness.agent.meta_tools.skills.market.skill_market_tool import (
    _handle_install,
    _handle_install_from_url,
)
from myrm_agent_harness.agent.skills.market.service import BaseSkillMarketService
from myrm_agent_harness.backends.skills.market_protocols import SkillInstallResult
from myrm_agent_harness.backends.skills.scanning import (
    ScanFinding,
    ScanResult,
    ScanSeverity,
    SkillTrustRecommendation,
    compute_scan_summary,
)


class TestCategoryCapScoring:
    """Tests for single-category deduction cap in compute_scan_summary."""

    def test_single_category_repeated_findings_capped_at_20(self) -> None:
        """10 repeated medium findings in the same category should only deduct at most 20 points."""
        findings = [
            ScanFinding(threat_type="network_access", severity=ScanSeverity.MEDIUM, description=f"curl {i}")
            for i in range(10)
        ]
        result = ScanResult(skill_name="repeat-cat", findings=findings)
        summary = compute_scan_summary(result)

        assert summary.trust_recommendation == "installed"
        # 100 - 20 (cap) = 80, in [50, 99]
        assert summary.score == 80
        assert summary.total_findings == 10

    def test_multiple_categories_accumulate_safely(self) -> None:
        """Different categories accumulate deductions independently up to the trust band."""
        findings = [
            ScanFinding(threat_type="network_access", severity=ScanSeverity.MEDIUM, description="fetch"),
            ScanFinding(threat_type="filesystem_access", severity=ScanSeverity.MEDIUM, description="read"),
            ScanFinding(threat_type="process_operation", severity=ScanSeverity.MEDIUM, description="proc"),
        ]
        result = ScanResult(skill_name="multi-cat", findings=findings)
        summary = compute_scan_summary(result)

        # 3 distinct categories with 1 medium (5 pts) each: 100 - 15 = 85
        assert summary.score == 85
        assert summary.trust_recommendation == "installed"

    def test_high_risk_findings_fall_below_50_gate(self) -> None:
        """High findings drop the trust band to untrusted (25-49), triggering the 50-point gate."""
        findings = [
            ScanFinding(threat_type="credential_exposure", severity=ScanSeverity.HIGH, description="AWS key read"),
        ]
        result = ScanResult(skill_name="high-risk", findings=findings)
        summary = compute_scan_summary(result)

        assert summary.trust_recommendation == "untrusted"
        assert summary.score < 50
        assert 25 <= summary.score <= 49


class TestPreflightSecurityGate:
    """Tests for 50-point preflight installation gate in BaseSkillMarketService."""

    @pytest.mark.asyncio
    async def test_skill_below_50_score_blocked_at_gate(self, tmp_path) -> None:
        svc = BaseSkillMarketService()
        files = {"SKILL.md": b"# untrusted\nimport os\n"}

        mock_scan = MagicMock()
        mock_scan.trust_recommendation = SkillTrustRecommendation.UNTRUSTED
        mock_scan.summary = "Detected credential exposure"
        mock_scan.is_clean = False
        mock_scan.findings = [
            ScanFinding(threat_type="credential_exposure", severity=ScanSeverity.HIGH, description="bad")
        ]
        mock_scan.ast_findings = []

        with (
            patch(
                "myrm_agent_harness.agent.skills.market.service.scan_all_text_files",
                return_value=mock_scan,
            ),
            patch(
                "myrm_agent_harness.agent.skills.market.service.LOCAL_INSTALL_DIR",
                tmp_path,
            ),
        ):
            res = await svc._quarantine_install("bad-id", "bad-skill", files, source="test")

            assert not res.success
            assert res.error_code == "SECURITY_SCORE_BELOW_THRESHOLD"
            assert "below 50 threshold" in res.error

    @pytest.mark.asyncio
    async def test_clean_skill_receives_100_score_receipt(self, tmp_path) -> None:
        svc = BaseSkillMarketService()
        files = {"SKILL.md": b"# clean\nSafe prompt instructions\n"}

        with patch(
            "myrm_agent_harness.agent.skills.market.service.LOCAL_INSTALL_DIR",
            tmp_path,
        ):
            res = await svc._quarantine_install("clean-id", "clean-skill", files, source="test")

            assert res.success
            assert res.receipt is not None
            assert res.receipt.scan_score == 100
            assert res.receipt.security_verified is True


class TestSkillMarketToolAntiRetry:
    """Tests for structured anti-retry instructions in Agent meta tool."""

    @pytest.mark.asyncio
    async def test_handle_install_returns_hard_stop_notice(self) -> None:
        backend = MagicMock()
        backend.install = AsyncMock(
            return_value=SkillInstallResult(
                success=False,
                skill_id="evil-plugin",
                skill_name="evil",
                error="Score 35/100 below 50 threshold",
                error_code="SECURITY_SCORE_BELOW_THRESHOLD",
            )
        )

        msg = await _handle_install(backend, "evil-plugin", "github", "user1")

        assert "Preflight Security Gate" in msg
        assert "Hard Stop Line" in msg
        assert "Do not attempt to retry" in msg

    @pytest.mark.asyncio
    async def test_handle_install_from_url_returns_hard_stop_notice(self) -> None:
        mock_install_fn = AsyncMock(
            return_value=SkillInstallResult(
                success=False,
                error="Score 20/100 below 50 threshold",
                error_code="SECURITY_SCORE_BELOW_THRESHOLD",
            )
        )

        msg = await _handle_install_from_url(mock_install_fn, "https://github.com/evil/repo", "user1")

        assert "Preflight Security Gate" in msg
        assert "Hard Stop Line" in msg
        assert "Do not attempt to retry" in msg
