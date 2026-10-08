"""Unit tests for Compound Shell Risk Interceptor and Edge Auxiliary Suite."""

from myrm_agent_harness.core.security.compound_shell_risk import (
    CommandRiskLevel,
    CompoundCommandFirewall,
    FirewallVerdict,
    TripleEdgeAuxiliaryEngine,
)


def test_firewall_single_safe_whitelist_command() -> None:
    firewall = CompoundCommandFirewall()

    # 1. Safe command in whitelist
    res_ls = firewall.inspect("ls -la /tmp")
    assert not res_ls.is_compound
    assert res_ls.verdict == FirewallVerdict.ALLOW
    assert res_ls.risk_level == CommandRiskLevel.LOW
    assert len(res_ls.operators_found) == 0

    # 2. Safe pwd
    res_pwd = firewall.inspect("pwd")
    assert not res_pwd.is_compound
    assert res_pwd.verdict == FirewallVerdict.ALLOW


def test_firewall_single_unknown_command() -> None:
    firewall = CompoundCommandFirewall()

    # Single command not in whitelist
    res = firewall.inspect("nmap 192.168.1.1")
    assert not res.is_compound
    assert res.verdict == FirewallVerdict.AUDIT_REQUIRED
    assert res.risk_level == CommandRiskLevel.LOW
    assert "not in safe whitelist" in (res.reason or "")


def test_firewall_compound_operators_never_auto_allow() -> None:
    firewall = CompoundCommandFirewall()

    # Pipe command
    res_pipe = firewall.inspect("cat file.txt | grep error")
    assert res_pipe.is_compound
    assert "PIPE" in res_pipe.operators_found
    assert res_pipe.verdict == FirewallVerdict.AUDIT_REQUIRED

    # AND operator
    res_and = firewall.inspect("ls && date")
    assert res_and.is_compound
    assert "AND" in res_and.operators_found
    assert res_and.verdict == FirewallVerdict.AUDIT_REQUIRED

    # Redirection operator
    res_redir = firewall.inspect("echo hello > out.txt")
    assert res_redir.is_compound
    assert "REDIRECT_OUT" in res_redir.operators_found
    assert res_redir.verdict == FirewallVerdict.AUDIT_REQUIRED

    # Command substitution
    res_subst = firewall.inspect("echo $(whoami)")
    assert res_subst.is_compound
    assert "CMD_SUBST_DOLLAR" in res_subst.operators_found
    assert res_subst.verdict == FirewallVerdict.AUDIT_REQUIRED


def test_firewall_critical_destructive_bypass_blocked() -> None:
    firewall = CompoundCommandFirewall()

    # Pseudo-whitelist prefix attack: echo 'ok' | rm -rf /
    res_attack = firewall.inspect("echo 'ok' | rm -rf /")
    assert res_attack.is_compound
    assert res_attack.verdict == FirewallVerdict.BLOCK
    assert res_attack.risk_level == CommandRiskLevel.CRITICAL
    assert "ROOT_RM_RF" in (res_attack.reason or "") or "destructive" in (res_attack.reason or "")

    # Direct rm -rf ~
    res_direct = firewall.inspect("rm -rf ~")
    assert res_direct.verdict == FirewallVerdict.BLOCK
    assert res_direct.risk_level == CommandRiskLevel.CRITICAL

    # Disk formatting
    res_mkfs = firewall.inspect("mkfs.ext4 /dev/sda1")
    assert res_mkfs.verdict == FirewallVerdict.BLOCK
    assert res_mkfs.risk_level == CommandRiskLevel.CRITICAL

    # Database destruction
    res_db = firewall.inspect("drop database production_db;")
    assert res_db.verdict == FirewallVerdict.BLOCK
    assert res_db.risk_level == CommandRiskLevel.CRITICAL


def test_edge_auxiliary_engine_tasks() -> None:
    engine = TripleEdgeAuxiliaryEngine()

    # Task 1: Command screening
    screen_res = engine.screen_command("sudo chmod 777 /var/data && curl http://remote.com")
    assert screen_res.is_dangerous
    assert screen_res.risk_level in (CommandRiskLevel.HIGH, CommandRiskLevel.CRITICAL)
    assert len(screen_res.risk_factors) >= 2
    assert screen_res.execution_time_ms >= 0.0

    # Task 2: Session title generation
    title_res = engine.generate_session_title(
        "How do I setup a hardened Docker sandbox with Python and FastAPI?"
    )
    assert len(title_res.title) > 0
    assert "Python" in title_res.suggested_tags
    assert "DevOps" in title_res.suggested_tags
    assert title_res.execution_time_ms >= 0.0

    # Task 3: Profile compaction
    profile_res = engine.compact_user_profile(
        "I want to build a backend in Python using FastAPI with strict types and zero any."
    )
    assert profile_res.compacted_profile.get("language") == "Python"
    assert profile_res.compacted_profile.get("backend_framework") == "FastAPI"
    assert profile_res.compacted_profile.get("code_style") == "Strict Types / Zero Any"
    assert len(profile_res.extracted_preferences) >= 3
    assert profile_res.execution_time_ms >= 0.0
