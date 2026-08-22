"""Tests for rescan_engine.py and AdvisoryAckRegistry."""

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from myrm_agent_harness.backends.skills.scanning.rescan_engine import (
    AdvisoryAckRegistry,
    InstalledSkillRescanEngine,
    SkillRescanResult,
)
from myrm_agent_harness.backends.skills.scanning.scanner import (
    ScanFinding,
    ScanSeverity,
    SkillTrustRecommendation,
)
from myrm_agent_harness.backends.skills.scanning.security_advisories import AdvisoryFinding


def test_advisory_ack_registry(tmp_path: Path) -> None:
    registry = AdvisoryAckRegistry()
    assert registry.is_acked("MAL-2021-001", "ua-parser-js") is False

    ack = registry.ack_advisory("MAL-2021-001", "ua-parser-js", "Confirmed safe in internal sandbox")
    assert ack.advisory_id == "MAL-2021-001"
    assert registry.is_acked("MAL-2021-001", "ua-parser-js") is True

    # Persist & reload
    ack_file = tmp_path / "acks.json"
    assert registry.save_to_disk(ack_file) is True
    assert ack_file.exists()

    new_reg = AdvisoryAckRegistry()
    assert new_reg.load_from_disk(ack_file) is True
    assert new_reg.is_acked("MAL-2021-001", "ua-parser-js") is True

    # Unack
    assert new_reg.unack_advisory("MAL-2021-001", "ua-parser-js") is True
    assert new_reg.is_acked("MAL-2021-001", "ua-parser-js") is False


@pytest.mark.asyncio
async def test_rescan_skill_directory_clean(tmp_path: Path) -> None:
    skill_dir = tmp_path / "clean-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("# Clean Skill\nDoes safe stuff.", encoding="utf-8")
    (skill_dir / "package.json").write_text('{"dependencies": {"safe-pkg": "1.0.0"}}', encoding="utf-8")

    engine = InstalledSkillRescanEngine()
    with patch("myrm_agent_harness.backends.skills.scanning.rescan_engine.query_osv_batch", AsyncMock(return_value=[])):
        res = await engine.rescan_skill_directory(skill_dir)
        assert res.is_clean is True
        assert res.recommendation == SkillTrustRecommendation.TRUSTED
        assert res.has_critical_or_malware is False


@pytest.mark.asyncio
async def test_rescan_skill_directory_with_compromised_dep(tmp_path: Path) -> None:
    skill_dir = tmp_path / "evil-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("# Evil Skill", encoding="utf-8")
    (skill_dir / "package.json").write_text('{"dependencies": {"event-stream": "3.3.6"}}', encoding="utf-8")

    engine = InstalledSkillRescanEngine()
    with patch("myrm_agent_harness.backends.skills.scanning.rescan_engine.query_osv_batch", AsyncMock(return_value=[])):
        res = await engine.rescan_skill_directory(skill_dir)
        assert res.is_clean is False
        assert res.recommendation == SkillTrustRecommendation.REJECT
        assert res.has_critical_or_malware is True
        assert len(res.advisory_findings) == 1
        assert res.advisory_findings[0].advisory_id == "MAL-2018-001"

        # Now acknowledge the advisory and rescan
        engine.ack_registry.ack_advisory("MAL-2018-001", "event-stream", "Sandbox isolated")
        res_acked = await engine.rescan_skill_directory(skill_dir)
        assert len(res_acked.unacked_advisory_findings) == 0
        assert len(res_acked.acked_advisory_findings) == 1
        assert res_acked.has_critical_or_malware is False


@pytest.mark.asyncio
async def test_rescan_in_memory_files() -> None:
    files = {
        "SKILL.md": b"# Test Skill",
        "requirements.txt": b"ctx==0.1.2\n",
    }
    engine = InstalledSkillRescanEngine()
    with patch("myrm_agent_harness.backends.skills.scanning.rescan_engine.query_osv_batch", AsyncMock(return_value=[])):
        res = await engine.rescan_in_memory_files("test-skill", files)
        assert res.has_critical_or_malware is True
        assert res.recommendation == SkillTrustRecommendation.REJECT
