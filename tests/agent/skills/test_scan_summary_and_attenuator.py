"""Unit tests for compute_scan_summary and scanner-gated trust attenuation."""

from myrm_agent_harness.agent.skills.runtime.attenuator import (
    INSTALLED_CEILING_TOOLS,
    READ_ONLY_TOOLS,
    attenuate_tools,
)
from myrm_agent_harness.backends.skills.scanning.scanner import (
    ScanFinding,
    ScanResult,
    ScanSeverity,
    compute_scan_summary,
)
from myrm_agent_harness.backends.skills.types import SecurityFindingDetail, SkillMetadata, SkillTrust

# ---------------------------------------------------------------------------
# compute_scan_summary
# ---------------------------------------------------------------------------


class TestComputeScanSummary:
    """Tests for compute_scan_summary score derivation."""

    def test_clean_scan_returns_100(self):
        result = ScanResult(skill_name="clean")
        summary = compute_scan_summary(result)

        assert summary.score == 100
        assert summary.trust_recommendation == "trusted"
        assert summary.total_findings == 0
        assert summary.finding_counts == {}

    def test_low_findings_stay_in_trusted_band(self):
        result = ScanResult(
            skill_name="low",
            findings=[
                ScanFinding("test", ScanSeverity.LOW, "minor issue"),
            ],
        )
        summary = compute_scan_summary(result)

        assert summary.trust_recommendation == "trusted"
        assert summary.score == 100  # band min=100, max=100
        assert summary.total_findings == 1

    def test_medium_findings_in_installed_band(self):
        result = ScanResult(
            skill_name="medium",
            findings=[
                ScanFinding("test", ScanSeverity.MEDIUM, "medium issue"),
            ],
        )
        summary = compute_scan_summary(result)

        assert summary.trust_recommendation == "installed"
        assert 50 <= summary.score <= 99
        assert summary.finding_counts.get("medium", 0) == 1

    def test_high_findings_in_untrusted_band(self):
        result = ScanResult(
            skill_name="high",
            findings=[
                ScanFinding("test", ScanSeverity.HIGH, "high issue"),
            ],
        )
        summary = compute_scan_summary(result)

        assert summary.trust_recommendation == "untrusted"
        assert 25 <= summary.score <= 49

    def test_critical_finding_in_reject_band(self):
        result = ScanResult(
            skill_name="critical",
            findings=[
                ScanFinding("test", ScanSeverity.CRITICAL, "critical issue"),
            ],
        )
        summary = compute_scan_summary(result)

        assert summary.trust_recommendation == "reject"
        assert 0 <= summary.score <= 24

    def test_multiple_findings_accumulate_deductions(self):
        result = ScanResult(
            skill_name="many",
            findings=[
                ScanFinding("a", ScanSeverity.MEDIUM, "issue 1"),
                ScanFinding("b", ScanSeverity.MEDIUM, "issue 2"),
                ScanFinding("c", ScanSeverity.MEDIUM, "issue 3"),
            ],
        )
        summary = compute_scan_summary(result)

        assert summary.trust_recommendation == "installed"
        # 100 - 15 = 85, within [50, 99]
        assert summary.score == 85
        assert summary.total_findings == 3

    def test_score_never_below_band_min(self):
        """Even with massive deductions, score stays within trust band."""
        result = ScanResult(
            skill_name="heavy", findings=[ScanFinding("a", ScanSeverity.CRITICAL, f"critical {i}") for i in range(10)]
        )
        summary = compute_scan_summary(result)

        assert summary.trust_recommendation == "reject"
        assert summary.score >= 0  # band min is 0

    def test_to_dict_roundtrip(self):
        result = ScanResult(
            skill_name="test",
            findings=[
                ScanFinding("cmd_injection", ScanSeverity.HIGH, "found rm -rf"),
            ],
        )
        summary = compute_scan_summary(result)
        d = summary.to_dict()

        assert d["score"] == summary.score
        assert d["trust_recommendation"] == summary.trust_recommendation
        assert d["finding_counts"] == summary.finding_counts
        assert d["total_findings"] == summary.total_findings

    def test_findings_detail_populated(self):
        """compute_scan_summary should populate SecurityFindingDetail list."""
        result = ScanResult(
            skill_name="detail",
            findings=[
                ScanFinding("cmd_injection", ScanSeverity.HIGH, "found rm -rf"),
                ScanFinding("data_exfil", ScanSeverity.MEDIUM, "suspicious fetch"),
            ],
        )
        summary = compute_scan_summary(result)

        assert len(summary.findings) == 2
        assert isinstance(summary.findings[0], SecurityFindingDetail)
        assert summary.findings[0].threat_type == "cmd_injection"
        assert summary.findings[0].severity == "high"
        assert summary.findings[1].threat_type == "data_exfil"
        assert summary.findings[1].severity == "medium"

    def test_to_dict_includes_findings(self):
        """to_dict should serialize findings details."""
        result = ScanResult(
            skill_name="detail",
            findings=[
                ScanFinding("eval_usage", ScanSeverity.LOW, "eval call"),
            ],
        )
        summary = compute_scan_summary(result)
        d = summary.to_dict()

        assert "findings" in d
        assert len(d["findings"]) == 1
        assert d["findings"][0]["threat_type"] == "eval_usage"
        assert d["findings"][0]["severity"] == "low"
        assert d["findings"][0]["description"] == "eval call"

    def test_clean_scan_findings_empty(self):
        """Clean scan should have empty findings tuple."""
        result = ScanResult(skill_name="clean")
        summary = compute_scan_summary(result)

        assert summary.findings == ()
        assert summary.to_dict()["findings"] == []


# ---------------------------------------------------------------------------
# attenuator: scanner-gated trust widening
# ---------------------------------------------------------------------------


ALL_TOOLS = sorted(INSTALLED_CEILING_TOOLS | {"bash_code_execute_tool", "code_exec_tool", "dangerous_tool"})


def _make_skill(trust: SkillTrust, scanner_clean: bool = True, allowed_tools: list[str] | None = None) -> SkillMetadata:
    return SkillMetadata(
        name="test_skill", description="test", trust=trust, scanner_clean=scanner_clean, allowed_tools=allowed_tools
    )


class TestAttenuatorScannerGating:
    """Tests for the three-tier INSTALLED trust attenuation logic."""

    def test_trusted_skill_gets_all_tools(self):
        skill = _make_skill(SkillTrust.TRUSTED)
        result = attenuate_tools(ALL_TOOLS, [skill])

        assert set(result.tool_names) == set(ALL_TOOLS)
        assert result.min_trust == SkillTrust.TRUSTED

    def test_installed_unclean_gets_readonly_ceiling(self):
        """INSTALLED skill with scanner findings → trust ceiling = READ_ONLY.

        allowed_tools filter then further restricts to declared tools.
        """
        skill = _make_skill(
            SkillTrust.INSTALLED, scanner_clean=False, allowed_tools=["file_write_tool", "web_search_tool"]
        )
        result = attenuate_tools(ALL_TOOLS, [skill])

        # Trust ceiling is READ_ONLY, allowed_tools then intersects.
        # Since file_write_tool/web_search_tool are not in READ_ONLY → empty.
        assert set(result.tool_names) == set()

    def test_installed_unclean_no_allowed_tools_gets_readonly(self):
        """INSTALLED skill with findings and no allowed_tools → full READ_ONLY."""
        skill = _make_skill(SkillTrust.INSTALLED, scanner_clean=False, allowed_tools=None)
        result = attenuate_tools(ALL_TOOLS, [skill])

        # No allowed_tools → allowed_tools filter skipped → full READ_ONLY
        assert set(result.tool_names) == READ_ONLY_TOOLS

    def test_installed_clean_no_allowed_tools_gets_readonly(self):
        """INSTALLED clean skill without allowed_tools → READ_ONLY only.

        Scanner-gated widening requires both scanner_clean AND allowed_tools.
        Without allowed_tools, falls back to READ_ONLY, then allowed_tools
        filter is skipped (no declaration), so full READ_ONLY is returned.
        """
        skill = _make_skill(SkillTrust.INSTALLED, scanner_clean=True, allowed_tools=None)
        result = attenuate_tools(ALL_TOOLS, [skill])

        assert set(result.tool_names) == READ_ONLY_TOOLS

    def test_installed_clean_with_allowed_gets_widened(self):
        """INSTALLED + clean + allowed_tools → widened then allowed_tools filter.

        Trust filter widens to (allowed ∩ CEILING) ∪ READ_ONLY,
        then allowed_tools filter intersects with declared tools.
        Final result = allowed_tools ∩ INSTALLED_CEILING_TOOLS
        (READ_ONLY tools are removed if not in allowed_tools declaration).
        """
        skill = _make_skill(
            SkillTrust.INSTALLED, scanner_clean=True, allowed_tools=["file_write_tool", "web_search_tool", "bash_code_execute_tool"]
        )
        result = attenuate_tools(ALL_TOOLS, [skill])

        tool_set = set(result.tool_names)
        # file_write_tool and web_search_tool are in CEILING → granted
        assert "file_write_tool" in tool_set
        assert "web_search_tool" in tool_set
        # bash_tool is NOT in CEILING → never granted
        assert "bash_code_execute_tool" not in tool_set
        # READ_ONLY tools are not in allowed_tools → filtered out
        assert tool_set == {"file_write_tool", "web_search_tool"}

    def test_installed_clean_with_readonly_in_allowed(self):
        """INSTALLED + clean + allowed_tools including READ_ONLY tools."""
        skill = _make_skill(
            SkillTrust.INSTALLED, scanner_clean=True, allowed_tools=["file_write_tool", "memory_search", "time_tool"]
        )
        result = attenuate_tools(ALL_TOOLS, [skill])

        tool_set = set(result.tool_names)
        # All three are in CEILING → granted, and allowed_tools keeps them
        assert "file_write_tool" in tool_set
        assert "memory_search" in tool_set
        assert "time_tool" in tool_set

    def test_installed_ceiling_never_grants_shell(self):
        """INSTALLED_CEILING_TOOLS should not contain dangerous shell tools."""
        dangerous = {"bash_code_execute_tool", "shell_tool", "terminal_tool", "code_exec_tool"}
        assert not (INSTALLED_CEILING_TOOLS & dangerous)

    def test_readonly_is_subset_of_ceiling(self):
        """READ_ONLY_TOOLS must be a subset of INSTALLED_CEILING_TOOLS."""
        assert READ_ONLY_TOOLS <= INSTALLED_CEILING_TOOLS

    def test_mixed_installed_one_unclean_degrades_all(self):
        """If any INSTALLED skill is unclean, trust ceiling = READ_ONLY.

        Both skills have allowed_tools, so allowed_tools filter applies
        with union = {file_write_tool, web_search_tool}.
        Since neither is in READ_ONLY → final result is empty.
        """
        clean = _make_skill(SkillTrust.INSTALLED, scanner_clean=True, allowed_tools=["file_write_tool"])
        dirty = _make_skill(SkillTrust.INSTALLED, scanner_clean=False, allowed_tools=["web_search_tool"])
        result = attenuate_tools(ALL_TOOLS, [clean, dirty])

        assert set(result.tool_names) == set()

    def test_mixed_installed_one_unclean_no_allowed_tools(self):
        """If any INSTALLED skill is unclean and no allowed_tools → READ_ONLY."""
        clean = _make_skill(SkillTrust.INSTALLED, scanner_clean=True, allowed_tools=None)
        dirty = _make_skill(SkillTrust.INSTALLED, scanner_clean=False, allowed_tools=None)
        result = attenuate_tools(ALL_TOOLS, [clean, dirty])

        # No allowed_tools → filter skipped → full READ_ONLY
        assert set(result.tool_names) == READ_ONLY_TOOLS

    def test_installed_widening_respects_ceiling(self):
        """Widened tools must be within INSTALLED_CEILING_TOOLS."""
        skill = _make_skill(
            SkillTrust.INSTALLED, scanner_clean=True, allowed_tools=[*list(INSTALLED_CEILING_TOOLS), "bash_code_execute_tool"]
        )
        result = attenuate_tools(ALL_TOOLS, [skill])

        tool_set = set(result.tool_names)
        assert tool_set <= INSTALLED_CEILING_TOOLS

    def test_no_active_skills_all_tools(self):
        """No active skills → all tools available."""
        result = attenuate_tools(ALL_TOOLS, [])

        assert set(result.tool_names) == set(ALL_TOOLS)
        assert result.min_trust == SkillTrust.TRUSTED


# ---------------------------------------------------------------------------
# User trust override in SkillAgent._get_cached_skills
# ---------------------------------------------------------------------------


class TestUserTrustOverride:
    """Tests for trusted_skill_ids override in SkillAgent."""

    def test_installed_skill_elevated_to_trusted(self):
        """Skill in trusted_skill_ids should be elevated from INSTALLED to TRUSTED."""
        skill = SkillMetadata(
            name="my_skill", description="test", storage_skill_id="skill-123", trust=SkillTrust.INSTALLED
        )
        trusted_ids = frozenset(["skill-123"])

        if (skill.storage_skill_id or skill.name) in trusted_ids and skill.trust < SkillTrust.TRUSTED:
            skill.trust = SkillTrust.TRUSTED

        assert skill.trust == SkillTrust.TRUSTED

    def test_already_trusted_unchanged(self):
        """Already TRUSTED skill stays TRUSTED regardless of trusted_skill_ids."""
        skill = SkillMetadata(
            name="my_skill", description="test", storage_skill_id="skill-123", trust=SkillTrust.TRUSTED
        )
        trusted_ids = frozenset(["skill-123"])

        if (skill.storage_skill_id or skill.name) in trusted_ids and skill.trust < SkillTrust.TRUSTED:
            skill.trust = SkillTrust.TRUSTED

        assert skill.trust == SkillTrust.TRUSTED

    def test_no_match_stays_installed(self):
        """Skill not in trusted_skill_ids remains INSTALLED."""
        skill = SkillMetadata(
            name="my_skill", description="test", storage_skill_id="skill-456", trust=SkillTrust.INSTALLED
        )
        trusted_ids = frozenset(["skill-123"])

        if (skill.storage_skill_id or skill.name) in trusted_ids and skill.trust < SkillTrust.TRUSTED:
            skill.trust = SkillTrust.TRUSTED

        assert skill.trust == SkillTrust.INSTALLED

    def test_fallback_to_name_when_no_storage_id(self):
        """When storage_skill_id is None, name is used as fallback for trust lookup."""
        skill = SkillMetadata(name="my_skill", description="test", trust=SkillTrust.INSTALLED)
        trusted_ids = frozenset(["my_skill"])

        sid = skill.storage_skill_id or skill.name
        if sid in trusted_ids and skill.trust < SkillTrust.TRUSTED:
            skill.trust = SkillTrust.TRUSTED

        assert skill.trust == SkillTrust.TRUSTED
