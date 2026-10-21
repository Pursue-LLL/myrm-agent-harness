"""Comprehensive Edge Cases, Malicious Syntax & Adversarial Tests for Skill Scanning & Rescan."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from myrm_agent_harness.backends.skills.scanning.dependency_extractor import (
    DeclaredDependency,
    extract_dependencies_from_package_json,
    extract_dependencies_from_pyproject_toml,
    extract_dependencies_from_requirements_txt,
    extract_skill_dependencies,
)
from myrm_agent_harness.backends.skills.scanning.osv_scanner import (
    parse_osv_severity,
    query_osv_batch,
)
from myrm_agent_harness.backends.skills.scanning.rescan_engine import (
    InstalledSkillRescanEngine,
)
from myrm_agent_harness.backends.skills.scanning.scanner import (
    ScanSeverity,
    SkillTrustRecommendation,
)
from myrm_agent_harness.backends.skills.scanning.vuln_cache import VulnScanCache


def test_dependency_extractor_adversarial_inputs() -> None:
    """Test extractor resilience against malformed, malicious and tricky manifests."""
    # 1. Truncated & deeply nested / invalid JSON in package.json
    assert extract_dependencies_from_package_json('{"dependencies": {"foo":') == []
    assert extract_dependencies_from_package_json("12345") == []
    assert extract_dependencies_from_package_json('{"dependencies": "not a dict"}') == []
    assert extract_dependencies_from_package_json('{"dependencies": {"": "1.0.0"}}') == []
    assert extract_dependencies_from_package_json('{"dependencies": {"safe": null}}')[0].version_spec == ""

    # 2. Malformed requirements.txt with complex comments, strange whitespace, invalid lines
    malformed_reqs = """
    # Full comment line
       # Indented comment
    pkg1 >= 1.0.0, < 2.0.0 ; python_version > '3.7' # trailing comment
    pkg2[extra1, extra2] == 0.5.2
    -e git+https://github.com/foo/bar.git#egg=bar
    --trusted-host pypi.org
    ../../../etc/passwd
    ???invalid-pkg-name???
    """
    deps = extract_dependencies_from_requirements_txt(malformed_reqs)
    names = {d.name: d.version_spec for d in deps}
    assert "pkg1" in names
    assert names["pkg1"] == ">= 1.0.0, < 2.0.0"
    assert "pkg2" in names
    assert names["pkg2"] == "== 0.5.2"
    assert "???invalid-pkg-name???" not in names

    # 3. pyproject.toml edge cases: empty strings, null tables, invalid types
    weird_toml = """
    [project]
    dependencies = ["valid-pkg>=1.0.0", "", 1234, "   "]
    optional-dependencies = { test = ["pytest"], invalid = 42 }

    [tool.poetry]
    dependencies = { python = "^3.10", "weird-pkg" = {} }
    """
    toml_deps = extract_dependencies_from_pyproject_toml(weird_toml)
    t_names = {d.name for d in toml_deps}
    assert "valid-pkg" in t_names
    assert "pytest" in t_names
    assert "weird-pkg" in t_names
    assert "python" not in t_names


def test_dependency_extractor_symlink_and_deep_recursion(tmp_path: Path) -> None:
    """Test recursion limits and ignored paths in disk directory scanning."""
    skill_dir = tmp_path / "deep-skill"
    skill_dir.mkdir()

    # Create ignored directories
    node_modules = skill_dir / "node_modules"
    node_modules.mkdir()
    (node_modules / "package.json").write_text('{"dependencies": {"ignore-me": "1.0"}}', encoding="utf-8")

    git_dir = skill_dir / ".git"
    git_dir.mkdir()
    (git_dir / "requirements.txt").write_text("ignore-git==1.0\n", encoding="utf-8")

    # Create root valid manifest
    (skill_dir / "package.json").write_text('{"dependencies": {"real-dep": "2.0"}}', encoding="utf-8")

    deps = extract_skill_dependencies(skill_dir)
    dep_names = {d.name for d in deps}
    assert "real-dep" in dep_names
    assert "ignore-me" not in dep_names
    assert "ignore-git" not in dep_names


def test_osv_severity_parsing_variations() -> None:
    """Test all possible OSV score/severity structures."""
    # 1. MAL- prefix
    assert parse_osv_severity({"id": "MAL-2023-1234"}) == ScanSeverity.CRITICAL

    # 2. database_specific variations
    assert parse_osv_severity({"database_specific": {"severity": "CRITICAL"}}) == ScanSeverity.CRITICAL
    assert parse_osv_severity({"database_specific": {"severity": "HIGH"}}) == ScanSeverity.HIGH
    assert parse_osv_severity({"database_specific": {"severity": "MODERATE"}}) == ScanSeverity.MEDIUM
    assert parse_osv_severity({"database_specific": {"severity": "LOW"}}) == ScanSeverity.LOW

    # 3. CVSS score string parsing
    assert parse_osv_severity({"severity": [{"score": "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H (9.8)"}]}) == ScanSeverity.CRITICAL
    assert parse_osv_severity({"severity": [{"score": "CVSS:3.0/AV:N (7.5)"}]}) == ScanSeverity.HIGH
    assert parse_osv_severity({"severity": [{"score": "5.5"}]}) == ScanSeverity.MEDIUM
    assert parse_osv_severity({"severity": [{"score": "2.1"}]}) == ScanSeverity.LOW
    assert parse_osv_severity({"severity": [{"score": "not a number"}]}) == ScanSeverity.MEDIUM
    assert parse_osv_severity({}) == ScanSeverity.MEDIUM


@pytest.mark.asyncio
async def test_rescan_engine_empty_and_broken_directories(tmp_path: Path) -> None:
    """Test rescan engine against non-existent or empty directories."""
    engine = InstalledSkillRescanEngine()

    # 1. Non-existent directory
    res_none = await engine.rescan_skill_directory(tmp_path / "does_not_exist")
    assert res_none.is_clean is True
    assert res_none.recommendation == SkillTrustRecommendation.TRUSTED

    # 2. Empty directory
    empty_dir = tmp_path / "empty_skill"
    empty_dir.mkdir()
    res_empty = await engine.rescan_skill_directory(empty_dir)
    assert res_empty.is_clean is True
    assert res_empty.recommendation == SkillTrustRecommendation.TRUSTED
    assert len(res_empty.declared_dependencies) == 0


@pytest.mark.asyncio
async def test_osv_scanner_batch_chunking_and_error_isolation() -> None:
    """Test OSV batch scanner splitting >100 queries properly and handling network failures cleanly."""
    deps = [
        DeclaredDependency(name=f"pkg-{i}", version_spec="1.0.0", ecosystem="npm")
        for i in range(120)
    ]
    cache = VulnScanCache()

    # Simulate network failure on second chunk
    call_count = 0

    async def _mock_post(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            mock_resp = AsyncMock()
            mock_resp.raise_for_status = MagicMock()
            mock_resp.json = MagicMock(return_value={"results": [{"vulns": []}] * 100})
            return mock_resp
        raise ConnectionResetError("Connection reset by peer")

    from unittest.mock import MagicMock
    mock_client = AsyncMock()
    mock_client.__aenter__.return_value.post = _mock_post

    with patch("myrm_agent_harness.backends.skills.scanning.osv_scanner.create_httpx_client", return_value=mock_client):
        findings = await query_osv_batch(deps, cache=cache)
        assert call_count == 2
        # First chunk succeeded, second failed gracefully without raising
        assert isinstance(findings, list)
