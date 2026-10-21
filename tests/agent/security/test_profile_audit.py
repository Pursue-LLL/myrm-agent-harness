"""Tests for security.profile_audit module — engine, scoring, and all checkers."""

from myrm_agent_harness.agent.security.profile_audit import (
    AuditFinding,
    AuditSeverity,
    ProfileAuditInput,
    RiskLevel,
    run_profile_audit,
)
from myrm_agent_harness.agent.security.profile_audit.scoring import compute_score
from myrm_agent_harness.agent.security.profile_audit.types import (
    CronJobInput,
    MCPConfigInput,
    SecurityPolicyInput,
    SkillScanInput,
    SubagentInput,
)


class TestAuditSeverity:
    def test_ordering(self):
        assert AuditSeverity.CRITICAL > AuditSeverity.HIGH
        assert AuditSeverity.HIGH > AuditSeverity.MEDIUM
        assert AuditSeverity.MEDIUM > AuditSeverity.LOW
        assert AuditSeverity.LOW > AuditSeverity.INFO

    def test_int_values(self):
        assert int(AuditSeverity.INFO) == 0
        assert int(AuditSeverity.CRITICAL) == 4


class TestScoring:
    def test_empty_findings_perfect_score(self):
        score, level, counts = compute_score(())
        assert score == 100
        assert level == RiskLevel.SAFE
        assert counts == {}

    def test_single_critical_deduction(self):
        findings = (
            AuditFinding(
                checker="test",
                severity=AuditSeverity.CRITICAL,
                title="t",
                description="d",
                recommendation="r",
            ),
        )
        score, level, counts = compute_score(findings)
        assert score == 70
        assert level == RiskLevel.LOW
        assert counts == {"critical": 1}

    def test_multiple_findings_cumulative(self):
        findings = (
            AuditFinding(checker="a", severity=AuditSeverity.HIGH, title="", description="", recommendation=""),
            AuditFinding(checker="b", severity=AuditSeverity.HIGH, title="", description="", recommendation=""),
            AuditFinding(checker="c", severity=AuditSeverity.MEDIUM, title="", description="", recommendation=""),
        )
        score, level, counts = compute_score(findings)
        assert score == 100 - 15 - 15 - 8  # 62
        assert level == RiskLevel.MEDIUM
        assert counts == {"high": 2, "medium": 1}

    def test_score_floors_at_zero(self):
        findings = tuple(
            AuditFinding(checker="x", severity=AuditSeverity.CRITICAL, title="", description="", recommendation="")
            for _ in range(5)
        )
        score, level, _ = compute_score(findings)
        assert score == 0
        assert level == RiskLevel.CRITICAL

    def test_risk_level_thresholds(self):
        assert compute_score(())[1] == RiskLevel.SAFE  # 100
        low_findings = (
            AuditFinding(checker="x", severity=AuditSeverity.CRITICAL, title="", description="", recommendation=""),
        )
        assert compute_score(low_findings)[1] == RiskLevel.LOW  # 70

    def test_info_findings_no_deduction(self):
        findings = tuple(
            AuditFinding(checker="x", severity=AuditSeverity.INFO, title="", description="", recommendation="")
            for _ in range(10)
        )
        score, level, counts = compute_score(findings)
        assert score == 100
        assert level == RiskLevel.SAFE
        assert counts == {"info": 10}


class TestEngine:
    def test_empty_profile_safe(self):
        result = run_profile_audit(ProfileAuditInput(agent_id="a1", agent_name="Test"))
        assert result.score == 100
        assert result.risk_level == RiskLevel.SAFE
        assert result.total_findings == 0

    def test_findings_sorted_by_severity_descending(self):
        audit_input = ProfileAuditInput(
            agent_id="a1",
            agent_name="Test",
            enabled_builtin_tools=("shell_exec", "file_write", "mcp_invoke", "net_fetch"),
            security_policy=SecurityPolicyInput(),
        )
        result = run_profile_audit(audit_input)
        assert result.total_findings > 0
        severities = [f.severity for f in result.findings]
        assert severities == sorted(severities, reverse=True)

    def test_result_to_dict(self):
        result = run_profile_audit(ProfileAuditInput(agent_id="a1", agent_name="Test"))
        d = result.to_dict()
        assert "score" in d
        assert "risk_level" in d
        assert "findings" in d
        assert isinstance(d["findings"], list)

    def test_dangerous_tool_combo_detected(self):
        audit_input = ProfileAuditInput(
            agent_id="a1",
            agent_name="Test",
            enabled_builtin_tools=("shell_exec", "file_write", "mcp_invoke"),
        )
        result = run_profile_audit(audit_input)
        tool_findings = [f for f in result.findings if f.checker == "tool_exposure"]
        assert len(tool_findings) > 0
        assert any("Dangerous tool combination" in f.title for f in tool_findings)


class TestToolExposureChecker:
    def test_no_tools_no_findings(self):
        result = run_profile_audit(ProfileAuditInput(agent_id="a1", agent_name="Test", enabled_builtin_tools=()))
        tool_findings = [f for f in result.findings if f.checker == "tool_exposure"]
        assert tool_findings == []

    def test_single_safe_tool(self):
        result = run_profile_audit(
            ProfileAuditInput(agent_id="a1", agent_name="Test", enabled_builtin_tools=("file_read",))
        )
        tool_findings = [f for f in result.findings if f.checker == "tool_exposure"]
        assert tool_findings == []

    def test_large_surface_with_high_priv(self):
        tools = ("shell_exec", "file_read", "file_write", "net_fetch", "web_search_tool")
        result = run_profile_audit(ProfileAuditInput(agent_id="a1", agent_name="Test", enabled_builtin_tools=tools))
        tool_findings = [f for f in result.findings if f.checker == "tool_exposure"]
        assert any("Large tool surface" in f.title for f in tool_findings)


class TestMCPAuthChecker:
    def test_no_mcps_no_findings(self):
        result = run_profile_audit(ProfileAuditInput(agent_id="a1", agent_name="Test", mcp_configs=()))
        mcp_findings = [f for f in result.findings if f.checker == "mcp_auth"]
        assert mcp_findings == []

    def test_stdio_no_auth_high_severity(self):
        mcp = MCPConfigInput(server_name="local-mcp", transport_type="stdio", has_auth=False)
        result = run_profile_audit(ProfileAuditInput(agent_id="a1", agent_name="Test", mcp_configs=(mcp,)))
        mcp_findings = [f for f in result.findings if f.checker == "mcp_auth"]
        assert any(f.severity == AuditSeverity.HIGH for f in mcp_findings)

    def test_streamable_http_no_auth_medium(self):
        mcp = MCPConfigInput(server_name="remote", transport_type="streamable-http", has_auth=False)
        result = run_profile_audit(ProfileAuditInput(agent_id="a1", agent_name="Test", mcp_configs=(mcp,)))
        mcp_findings = [f for f in result.findings if f.checker == "mcp_auth"]
        assert any(f.severity == AuditSeverity.MEDIUM for f in mcp_findings)

    def test_authenticated_mcp_no_finding(self):
        mcp = MCPConfigInput(server_name="secure", transport_type="stdio", has_auth=True)
        result = run_profile_audit(ProfileAuditInput(agent_id="a1", agent_name="Test", mcp_configs=(mcp,)))
        mcp_findings = [f for f in result.findings if f.checker == "mcp_auth"]
        assert mcp_findings == []

    def test_high_severity_scan_findings(self):
        mcp = MCPConfigInput(
            server_name="bad", transport_type="streamable-http", has_auth=True, finding_count=5, max_severity="critical"
        )
        result = run_profile_audit(ProfileAuditInput(agent_id="a1", agent_name="Test", mcp_configs=(mcp,)))
        mcp_findings = [f for f in result.findings if f.checker == "mcp_auth"]
        assert any("scan findings" in f.title for f in mcp_findings)


class TestSkillAggregateChecker:
    def test_no_skills_no_findings(self):
        result = run_profile_audit(ProfileAuditInput(agent_id="a1", agent_name="Test", skill_scans=()))
        skill_findings = [f for f in result.findings if f.checker == "skill_aggregate"]
        assert skill_findings == []

    def test_rejected_skill_critical(self):
        skill = SkillScanInput(skill_id="s1", skill_name="bad_skill", score=20, trust_recommendation="reject")
        result = run_profile_audit(ProfileAuditInput(agent_id="a1", agent_name="Test", skill_scans=(skill,)))
        skill_findings = [f for f in result.findings if f.checker == "skill_aggregate"]
        assert any(f.severity == AuditSeverity.CRITICAL for f in skill_findings)

    def test_untrusted_skill_high(self):
        skill = SkillScanInput(skill_id="s2", skill_name="sus_skill", score=30, trust_recommendation="untrusted")
        result = run_profile_audit(ProfileAuditInput(agent_id="a1", agent_name="Test", skill_scans=(skill,)))
        skill_findings = [f for f in result.findings if f.checker == "skill_aggregate"]
        assert any(f.severity == AuditSeverity.HIGH for f in skill_findings)

    def test_low_score_skill_medium(self):
        skill = SkillScanInput(skill_id="s3", skill_name="meh_skill", score=50, trust_recommendation="caution")
        result = run_profile_audit(ProfileAuditInput(agent_id="a1", agent_name="Test", skill_scans=(skill,)))
        skill_findings = [f for f in result.findings if f.checker == "skill_aggregate"]
        assert any(f.severity == AuditSeverity.MEDIUM for f in skill_findings)

    def test_safe_skill_no_finding(self):
        skill = SkillScanInput(skill_id="s4", skill_name="good_skill", score=90, trust_recommendation="trusted")
        result = run_profile_audit(ProfileAuditInput(agent_id="a1", agent_name="Test", skill_scans=(skill,)))
        skill_findings = [f for f in result.findings if f.checker == "skill_aggregate"]
        assert skill_findings == []


class TestSubagentRiskChecker:
    def test_no_subagents_no_findings(self):
        result = run_profile_audit(ProfileAuditInput(agent_id="a1", agent_name="Test", subagents=()))
        sub_findings = [f for f in result.findings if f.checker == "subagent_risk"]
        assert sub_findings == []

    def test_nested_subagent_high(self):
        sub = SubagentInput(agent_id="sub1", agent_name="nested", has_own_subagents=True)
        result = run_profile_audit(ProfileAuditInput(agent_id="a1", agent_name="Test", subagents=(sub,)))
        sub_findings = [f for f in result.findings if f.checker == "subagent_risk"]
        assert any(f.severity == AuditSeverity.HIGH for f in sub_findings)

    def test_many_subagents_low(self):
        subs = tuple(SubagentInput(agent_id=f"sub{i}", agent_name=f"s{i}") for i in range(5))
        result = run_profile_audit(ProfileAuditInput(agent_id="a1", agent_name="Test", subagents=subs))
        sub_findings = [f for f in result.findings if f.checker == "subagent_risk"]
        assert any(f.severity == AuditSeverity.LOW for f in sub_findings)


class TestCronRiskChecker:
    def test_no_crons_no_findings(self):
        result = run_profile_audit(ProfileAuditInput(agent_id="a1", agent_name="Test", cron_jobs=()))
        cron_findings = [f for f in result.findings if f.checker == "cron_risk"]
        assert cron_findings == []

    def test_dangerous_cron_high(self):
        job = CronJobInput(job_id="j1", schedule="0 * * * *", agent_id="a1", has_dangerous_tools=True)
        result = run_profile_audit(ProfileAuditInput(agent_id="a1", agent_name="Test", cron_jobs=(job,)))
        cron_findings = [f for f in result.findings if f.checker == "cron_risk"]
        assert any(f.severity == AuditSeverity.HIGH for f in cron_findings)

    def test_many_crons_low(self):
        jobs = tuple(CronJobInput(job_id=f"j{i}", schedule="* * * * *", agent_id="a1") for i in range(6))
        result = run_profile_audit(ProfileAuditInput(agent_id="a1", agent_name="Test", cron_jobs=jobs))
        cron_findings = [f for f in result.findings if f.checker == "cron_risk"]
        assert any(f.severity == AuditSeverity.LOW for f in cron_findings)


class TestPolicyGapChecker:
    def test_no_tools_no_gaps(self):
        result = run_profile_audit(ProfileAuditInput(agent_id="a1", agent_name="Test"))
        gap_findings = [f for f in result.findings if f.checker == "policy_gap"]
        assert gap_findings == []

    def test_network_tools_no_policy(self):
        result = run_profile_audit(
            ProfileAuditInput(
                agent_id="a1",
                agent_name="Test",
                enabled_builtin_tools=("net_fetch",),
                security_policy=SecurityPolicyInput(),
            )
        )
        gap_findings = [f for f in result.findings if f.checker == "policy_gap"]
        assert any("network policy" in f.title.lower() for f in gap_findings)

    def test_fs_tools_no_path_policy(self):
        result = run_profile_audit(
            ProfileAuditInput(
                agent_id="a1",
                agent_name="Test",
                enabled_builtin_tools=("file_write",),
                security_policy=SecurityPolicyInput(),
            )
        )
        gap_findings = [f for f in result.findings if f.checker == "policy_gap"]
        assert any("path policy" in f.title.lower() for f in gap_findings)

    def test_full_policy_no_gaps(self):
        result = run_profile_audit(
            ProfileAuditInput(
                agent_id="a1",
                agent_name="Test",
                enabled_builtin_tools=("net_fetch", "file_write", "shell_exec"),
                security_policy=SecurityPolicyInput(
                    has_path_policy=True,
                    has_network_policy=True,
                    has_capability_restrictions=True,
                    domain_hitl_enabled=True,
                ),
            )
        )
        gap_findings = [f for f in result.findings if f.checker == "policy_gap"]
        assert gap_findings == []


class TestIntegration:
    def test_full_profile_all_checkers_fire(self):
        audit_input = ProfileAuditInput(
            agent_id="a1",
            agent_name="Risky Agent",
            enabled_builtin_tools=("shell_exec", "file_write", "mcp_invoke", "net_fetch", "code_interpreter_tool"),
            mcp_configs=(MCPConfigInput(server_name="unsafe", transport_type="stdio", has_auth=False),),
            skill_scans=(SkillScanInput(skill_id="s1", skill_name="evil", score=10, trust_recommendation="reject"),),
            subagents=(
                SubagentInput(
                    agent_id="sub1", agent_name="deep", has_own_subagents=True, has_own_mcps=True, has_own_tools=True
                ),
            ),
            cron_jobs=(CronJobInput(job_id="j1", schedule="* * * * *", agent_id="a1", has_dangerous_tools=True),),
            security_policy=SecurityPolicyInput(),
        )
        result = run_profile_audit(audit_input)
        assert result.score < 50
        assert result.risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL)
        assert result.total_findings >= 6
        checkers_fired = {f.checker for f in result.findings}
        assert "tool_exposure" in checkers_fired
        assert "mcp_auth" in checkers_fired
        assert "skill_aggregate" in checkers_fired
        assert "subagent_risk" in checkers_fired
        assert "cron_risk" in checkers_fired
        assert "policy_gap" in checkers_fired

    def test_findings_severity_order_guaranteed(self):
        audit_input = ProfileAuditInput(
            agent_id="a1",
            agent_name="Mixed",
            enabled_builtin_tools=("shell_exec", "file_write", "mcp_invoke", "net_fetch"),
            mcp_configs=(MCPConfigInput(server_name="x", transport_type="stdio", has_auth=False),),
            skill_scans=(SkillScanInput(skill_id="s1", skill_name="bad", score=10, trust_recommendation="reject"),),
            security_policy=SecurityPolicyInput(),
        )
        result = run_profile_audit(audit_input)
        severities = [f.severity for f in result.findings]
        for i in range(len(severities) - 1):
            assert severities[i] >= severities[i + 1], (
                f"Finding {i} ({severities[i]}) < Finding {i + 1} ({severities[i + 1]})"
            )
