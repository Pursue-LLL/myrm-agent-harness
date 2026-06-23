"""Tests for security engine — wildcard-based rule evaluation."""

from __future__ import annotations

import os

from myrm_agent_harness.agent.security.checks import (
    _has_explicit_scheme,
    check_navigate_scheme,
    check_path_policy,
    check_shell_threats,
)
from myrm_agent_harness.agent.security.config import from_config, parse_security_config
from myrm_agent_harness.agent.security.engine import (
    _check_domain_policy,
    _domain_in_allowlist,
    _resolve_target,
    check_capability,
    disabled_permissions,
    evaluate,
    evaluate_tool_call,
    extract_url_domains,
    merge,
)
from myrm_agent_harness.agent.security.types import (
    DEFAULT_CAPABILITIES,
    DEFAULT_RULESET,
    Capability,
    PathPolicy,
    PermissionAction,
    PermissionRule,
    PermissionRuleset,
    SecurityConfig,
)


class TestEvaluate:
    def test_last_match_wins(self) -> None:
        ruleset = (
            PermissionRule("shell_exec", "*", PermissionAction.ALLOW),
            PermissionRule("shell_exec", "*", PermissionAction.DENY),
        )
        result = evaluate("shell_exec", "*", ruleset)
        assert result.action == PermissionAction.DENY

    def test_fallback_ask(self) -> None:
        result = evaluate("unknown_perm", "*", ())
        assert result.action == PermissionAction.ASK

    def test_wildcard_permission(self) -> None:
        ruleset = (PermissionRule("*", "*", PermissionAction.ALLOW),)
        result = evaluate("anything", "target", ruleset)
        assert result.action == PermissionAction.ALLOW

    def test_pattern_matching(self) -> None:
        ruleset = (PermissionRule("file_read", "*.env", PermissionAction.DENY),)
        result = evaluate("file_read", ".env", ruleset)
        assert result.action == PermissionAction.DENY

    def test_multiple_rulesets_merged(self) -> None:
        rs1 = (PermissionRule("shell_exec", "*", PermissionAction.ALLOW),)
        rs2 = (PermissionRule("shell_exec", "*", PermissionAction.DENY),)
        result = evaluate("shell_exec", "*", rs1, rs2)
        assert result.action == PermissionAction.DENY


class TestCheckCapability:
    def test_default_allows_all(self) -> None:
        assert check_capability("anything", "*", DEFAULT_CAPABILITIES) is True

    def test_empty_capabilities_deny(self) -> None:
        assert check_capability("shell_exec", "*", frozenset()) is False

    def test_specific_capability(self) -> None:
        caps = frozenset({Capability("file_read", "*.py")})
        assert check_capability("file_read", "test.py", caps) is True
        assert check_capability("file_write", "test.py", caps) is False

    def test_negative_capability(self) -> None:
        caps = frozenset(
            {
                Capability("*", "*"),
                Capability("!browser_navigate", "*"),
            }
        )
        assert check_capability("browser_navigate", "*", caps) is False
        assert check_capability("shell_exec", "*", caps) is True


class TestMerge:
    def test_empty(self) -> None:
        assert merge() == ()

    def test_single(self) -> None:
        rs = (PermissionRule("a", "*", PermissionAction.ALLOW),)
        assert merge(rs) == rs

    def test_order_preserved(self) -> None:
        rs1 = (PermissionRule("a", "*", PermissionAction.ALLOW),)
        rs2 = (PermissionRule("b", "*", PermissionAction.DENY),)
        result = merge(rs1, rs2)
        assert len(result) == 2
        assert result[0].permission == "a"
        assert result[1].permission == "b"


class TestFromConfig:
    def test_simple_format(self) -> None:
        rules = from_config({"shell_exec": "ask", "file_write": "deny"})
        assert len(rules) == 2
        shell = next(r for r in rules if r.permission == "shell_exec")
        assert shell.action == PermissionAction.ASK

    def test_nested_format(self) -> None:
        rules = from_config({"file_read": {"*": "allow", "*.env": "ask"}})
        assert len(rules) == 2


class TestParseSecurityConfig:
    def test_none_returns_none(self) -> None:
        assert parse_security_config(None) is None

    def test_empty_returns_none(self) -> None:
        assert parse_security_config({}) is None

    def test_timeout(self) -> None:
        config = parse_security_config({"approvalTimeoutSeconds": 60})
        assert config is not None
        assert config.approval_timeout_seconds == 60

    def test_capabilities(self) -> None:
        config = parse_security_config(
            {
                "capabilities": ["shell_exec", {"permission": "file_read", "pattern": "*.py"}],
            }
        )
        assert config is not None
        perms = {c.permission for c in config.capabilities}
        assert "shell_exec" in perms
        assert "file_read" in perms

    def test_permissions(self) -> None:
        config = parse_security_config(
            {
                "permissions": {"shell_exec": "deny"},
            }
        )
        assert config is not None
        shell_rules = [r for r in config.ruleset if r.permission == "shell_exec"]
        assert any(r.action == PermissionAction.DENY for r in shell_rules)

    def test_path_policy(self) -> None:
        config = parse_security_config(
            {
                "pathPolicy": {
                    "forbiddenPaths": ["/secret"],
                    "allowedRoots": ["/home/user"],
                },
            }
        )
        assert config is not None
        assert "/home/user" in config.path_policy.allowed_roots

    def test_network_allowlist(self) -> None:
        config = parse_security_config(
            {
                "networkAllowlist": ["api.example.com", " CDN.Example.COM "],
            }
        )
        assert config is not None
        assert "api.example.com" in config.network_allowlist
        assert "cdn.example.com" in config.network_allowlist


class TestHasExplicitScheme:
    def test_http(self) -> None:
        assert _has_explicit_scheme("http://example.com") is True

    def test_https(self) -> None:
        assert _has_explicit_scheme("https://example.com") is True

    def test_file(self) -> None:
        assert _has_explicit_scheme("file:///etc/passwd") is True

    def test_javascript(self) -> None:
        assert _has_explicit_scheme("javascript:alert(1)") is True

    def test_bare_hostname_port(self) -> None:
        assert _has_explicit_scheme("localhost:3000") is False

    def test_no_scheme(self) -> None:
        assert _has_explicit_scheme("example.com",) is False


class TestCheckNavigateScheme:
    def test_non_navigate_skipped(self) -> None:
        action, _ = check_navigate_scheme("shell_exec", {"url": "file:///etc"})
        assert action is None

    def test_http_allowed(self) -> None:
        action, _ = check_navigate_scheme("browser_navigate", {"url": "http://example.com"})
        assert action is None

    def test_file_blocked(self) -> None:
        action, _reason = check_navigate_scheme("browser_navigate", {"url": "file:///etc/passwd"})
        assert action == PermissionAction.DENY

    def test_javascript_blocked(self) -> None:
        action, _ = check_navigate_scheme("browser_navigate", {"url": "javascript:alert(1)"})
        assert action == PermissionAction.DENY

    def test_empty_url(self) -> None:
        action, _ = check_navigate_scheme("browser_navigate", {"url": ""})
        assert action is None


class TestCheckShellThreats:
    def test_non_shell_skipped(self) -> None:
        action, _ = check_shell_threats("file_read", {"command": "rm -rf /"})
        assert action is None

    def test_safe_command(self) -> None:
        action, _ = check_shell_threats("shell_exec", {"command": "ls -la"})
        assert action is None

    def test_dangerous_command(self) -> None:
        action, _reason = check_shell_threats("shell_exec", {"command": "rm -rf /"})
        assert action is not None

    def test_empty_command(self) -> None:
        action, _ = check_shell_threats("shell_exec", {"command": ""})
        assert action is None


class TestCheckPathPolicy:
    def test_forbidden_path_denied(self) -> None:
        policy = PathPolicy(forbidden_paths=frozenset({"/etc"}), allowed_roots=())
        action, _ = check_path_policy("/etc/passwd", policy, None)
        assert action == PermissionAction.DENY

    def test_allowed_root(self) -> None:
        policy = PathPolicy(forbidden_paths=frozenset(), allowed_roots=("/home/user",))
        action, _ = check_path_policy("/home/user/file.txt", policy, None)
        assert action == PermissionAction.ALLOW

    def test_workspace_root_allowed(self) -> None:
        policy = PathPolicy(forbidden_paths=frozenset(), allowed_roots=())
        action, _ = check_path_policy("/workspace/file.txt", policy, "/workspace")
        assert action == PermissionAction.ALLOW

    def test_outside_all_zones_asks(self) -> None:
        policy = PathPolicy(forbidden_paths=frozenset(), allowed_roots=())
        action, _ = check_path_policy("/random/path", policy, "/workspace")
        assert action == PermissionAction.ASK


class TestResolveTarget:
    def test_browser_navigate_extracts_host(self) -> None:
        target = _resolve_target("browser_navigate", {"url": "http://192.168.1.1/admin"})
        assert target == "192.168.1.1"

    def test_shell_exec_returns_command(self) -> None:
        target = _resolve_target("shell_exec", {"command": "ls -la"})
        assert target == "ls -la"

    def test_unknown_permission_returns_star(self) -> None:
        target = _resolve_target("unknown", {"data": "value"})
        assert target == "*"

    def test_missing_key_returns_star(self) -> None:
        target = _resolve_target("browser_navigate", {})
        assert target == "*"

    def test_mcp_invoke_uses_tool_name_as_target(self) -> None:
        target = _resolve_target("mcp_invoke", {"query": "test"}, tool_name="mcp__gmail__send_email")
        assert target == "mcp__gmail__send_email"

    def test_mcp_invoke_without_tool_name_returns_star(self) -> None:
        target = _resolve_target("mcp_invoke", {"query": "test"})
        assert target == "*"

    def test_mcp_invoke_empty_tool_name_returns_star(self) -> None:
        target = _resolve_target("mcp_invoke", {}, tool_name="")
        assert target == "*"


class TestMCPPerToolApproval:
    """Tests for per-MCP-tool approval via pattern matching in the ruleset."""

    def test_mcp_default_ask(self) -> None:
        """Default ruleset has mcp_invoke=ASK, so all MCP tools require approval."""
        config = SecurityConfig()
        action, _ = evaluate_tool_call("mcp_invoke", {}, config, tool_name="mcp__gmail__search_inbox")
        assert action == PermissionAction.ASK

    def test_mcp_per_tool_allow_with_wildcard_ask(self) -> None:
        """User configures: search_inbox=ALLOW, everything else=ASK."""
        user_rules: PermissionRuleset = (
            PermissionRule("mcp_invoke", "*", PermissionAction.ASK),
            PermissionRule("mcp_invoke", "mcp__gmail__search_inbox", PermissionAction.ALLOW),
        )
        config = SecurityConfig(ruleset=merge(DEFAULT_RULESET, user_rules))
        action_search, _ = evaluate_tool_call("mcp_invoke", {}, config, tool_name="mcp__gmail__search_inbox")
        assert action_search == PermissionAction.ALLOW

        action_send, _ = evaluate_tool_call("mcp_invoke", {}, config, tool_name="mcp__gmail__send_email")
        assert action_send == PermissionAction.ASK

    def test_mcp_per_tool_deny(self) -> None:
        """User denies a specific MCP tool."""
        user_rules: PermissionRuleset = (
            PermissionRule("mcp_invoke", "*", PermissionAction.ALLOW),
            PermissionRule("mcp_invoke", "mcp__slack__delete_message", PermissionAction.DENY),
        )
        config = SecurityConfig(ruleset=user_rules)
        action_delete, _ = evaluate_tool_call("mcp_invoke", {}, config, tool_name="mcp__slack__delete_message")
        assert action_delete == PermissionAction.DENY

        action_post, _ = evaluate_tool_call("mcp_invoke", {}, config, tool_name="mcp__slack__post_message")
        assert action_post == PermissionAction.ALLOW

    def test_mcp_wildcard_server_pattern(self) -> None:
        """User allows all tools from a specific MCP server via wildcard."""
        user_rules: PermissionRuleset = (
            PermissionRule("mcp_invoke", "*", PermissionAction.ASK),
            PermissionRule("mcp_invoke", "mcp__gmail__*", PermissionAction.ALLOW),
        )
        config = SecurityConfig(ruleset=user_rules)
        action_gmail, _ = evaluate_tool_call("mcp_invoke", {}, config, tool_name="mcp__gmail__search_inbox")
        assert action_gmail == PermissionAction.ALLOW

        action_slack, _ = evaluate_tool_call("mcp_invoke", {}, config, tool_name="mcp__slack__post_message")
        assert action_slack == PermissionAction.ASK

    def test_mcp_backward_compatible_without_tool_name(self) -> None:
        """Without tool_name, mcp_invoke still works with existing behavior (target='*')."""
        config = SecurityConfig()
        action, _ = evaluate_tool_call("mcp_invoke", {}, config)
        assert action == PermissionAction.ASK

    def test_mcp_last_match_wins(self) -> None:
        """Last-match-wins: later rule overrides earlier."""
        user_rules: PermissionRuleset = (
            PermissionRule("mcp_invoke", "*", PermissionAction.ALLOW),
            PermissionRule("mcp_invoke", "mcp__gmail__*", PermissionAction.DENY),
            PermissionRule("mcp_invoke", "mcp__gmail__search_inbox", PermissionAction.ALLOW),
        )
        config = SecurityConfig(ruleset=user_rules)
        action_search, _ = evaluate_tool_call("mcp_invoke", {}, config, tool_name="mcp__gmail__search_inbox")
        assert action_search == PermissionAction.ALLOW

        action_send, _ = evaluate_tool_call("mcp_invoke", {}, config, tool_name="mcp__gmail__send_email")
        assert action_send == PermissionAction.DENY

        action_slack, _ = evaluate_tool_call("mcp_invoke", {}, config, tool_name="mcp__slack__post")
        assert action_slack == PermissionAction.ALLOW


class TestEvaluateToolCall:
    def test_capability_denied(self) -> None:
        config = SecurityConfig(capabilities=frozenset())
        action, reason = evaluate_tool_call("shell_exec", {}, config)
        assert action == PermissionAction.DENY
        assert "capability" in reason.lower()

    def test_shell_threat_denied(self) -> None:
        config = SecurityConfig()
        action, _ = evaluate_tool_call("shell_exec", {"command": "rm -rf /"}, config)
        assert action in (PermissionAction.DENY, PermissionAction.ASK)

    def test_navigate_scheme_denied(self) -> None:
        config = SecurityConfig()
        action, _ = evaluate_tool_call("browser_navigate", {"url": "file:///etc"}, config)
        assert action == PermissionAction.DENY

    def test_path_policy_denied(self) -> None:
        config = SecurityConfig(path_policy=PathPolicy(forbidden_paths=frozenset({"/etc"}), allowed_roots=()))
        action, _ = evaluate_tool_call("file_read", {"path": "/etc/shadow"}, config)
        assert action == PermissionAction.DENY

    def test_normal_allow(self) -> None:
        config = SecurityConfig()
        action, _ = evaluate_tool_call("file_read", {"path": "."}, config, workspace_root=os.getcwd())
        assert action == PermissionAction.ALLOW

    def test_path_policy_ask_outside_workspace(self) -> None:
        config = SecurityConfig(path_policy=PathPolicy(forbidden_paths=frozenset(), allowed_roots=()))
        action, _ = evaluate_tool_call("file_read", {"path": "/random/path"}, config, workspace_root="/workspace")
        assert action == PermissionAction.ASK


class TestDisabledPermissions:
    def test_denied_by_capability(self) -> None:
        caps = frozenset({Capability("file_read", "*")})
        result = disabled_permissions(["file_read", "shell_exec"], DEFAULT_RULESET, caps)
        assert "shell_exec" in result

    def test_denied_by_ruleset(self) -> None:
        ruleset = (PermissionRule("shell_exec", "*", PermissionAction.DENY),)
        result = disabled_permissions(["shell_exec"], ruleset)
        assert "shell_exec" in result

    def test_allowed_not_in_result(self) -> None:
        result = disabled_permissions(["file_read"], DEFAULT_RULESET)
        assert "file_read" not in result


class TestDomainInAllowlist:
    """Tests for _domain_in_allowlist() — exact and suffix matching."""

    def test_exact_match(self) -> None:
        assert _domain_in_allowlist("example.com", ("example.com",)) is True

    def test_exact_no_match(self) -> None:
        assert _domain_in_allowlist("evil.com", ("example.com",)) is False

    def test_suffix_match_subdomain(self) -> None:
        assert _domain_in_allowlist("mail.google.com", (".google.com",)) is True

    def test_suffix_match_bare_domain(self) -> None:
        assert _domain_in_allowlist("google.com", (".google.com",)) is True

    def test_suffix_no_partial_match(self) -> None:
        assert _domain_in_allowlist("notgoogle.com", (".google.com",)) is False

    def test_case_insensitive(self) -> None:
        assert _domain_in_allowlist("EXAMPLE.COM", ("example.com",)) is True

    def test_empty_allowlist(self) -> None:
        assert _domain_in_allowlist("example.com", ()) is False

    def test_multiple_entries(self) -> None:
        allowlist = ("example.com", ".google.com", "localhost")
        assert _domain_in_allowlist("mail.google.com", allowlist) is True
        assert _domain_in_allowlist("localhost", allowlist) is True
        assert _domain_in_allowlist("evil.com", allowlist) is False


class TestCheckDomainPolicy:
    """Tests for _check_domain_policy() — Layer 2c domain HITL check."""

    def test_url_not_in_allowlist_triggers_ask(self) -> None:
        action, reason = _check_domain_policy("web_fetch", {"url": "https://evil.com/page"}, ("example.com",))
        assert action == PermissionAction.ASK
        assert "evil.com" in reason

    def test_url_in_allowlist_passes(self) -> None:
        action, _ = _check_domain_policy("web_fetch", {"url": "https://example.com/page"}, ("example.com",))
        assert action is None

    def test_non_url_permission_ignored(self) -> None:
        action, _ = _check_domain_policy("shell_exec", {"command": "curl https://evil.com"}, ("example.com",))
        assert action is None

    def test_empty_url_passes(self) -> None:
        action, _ = _check_domain_policy("web_fetch", {"url": ""}, ("example.com",))
        assert action is None

    def test_no_url_param_passes(self) -> None:
        action, _ = _check_domain_policy("web_fetch", {}, ("example.com",))
        assert action is None

    def test_browser_navigate_checked(self) -> None:
        action, reason = _check_domain_policy("browser_navigate", {"url": "https://unknown.com"}, ("example.com",))
        assert action == PermissionAction.ASK
        assert "unknown.com" in reason

    def test_suffix_match_in_allowlist(self) -> None:
        action, _ = _check_domain_policy("web_fetch", {"url": "https://api.google.com/v1"}, (".google.com",))
        assert action is None

    def test_net_fetch_triggers_domain_check(self) -> None:
        """net_fetch (production permission for web_fetch_tool) must also trigger domain checks."""
        action, reason = _check_domain_policy("net_fetch", {"url": "https://evil.com/page"}, ("example.com",))
        assert action == PermissionAction.ASK
        assert "evil.com" in reason

    def test_net_fetch_allowlist_passes(self) -> None:
        action, _ = _check_domain_policy("net_fetch", {"url": "https://example.com/page"}, ("example.com",))
        assert action is None


class TestExtractUrlDomains:
    """Tests for extract_url_domains() — public API for domain extraction."""

    def test_web_fetch_extracts_hostname(self) -> None:
        domains = extract_url_domains("web_fetch", {"url": "https://mail.google.com/inbox"})
        assert domains == ("mail.google.com",)

    def test_browser_navigate_extracts_hostname(self) -> None:
        domains = extract_url_domains("browser_navigate", {"url": "https://example.com/path"})
        assert domains == ("example.com",)

    def test_non_url_permission_returns_empty(self) -> None:
        assert extract_url_domains("shell_exec", {"command": "ls"}) == ()

    def test_missing_url_returns_empty(self) -> None:
        assert extract_url_domains("web_fetch", {}) == ()

    def test_empty_url_returns_empty(self) -> None:
        assert extract_url_domains("web_fetch", {"url": ""}) == ()

    def test_bare_hostname_with_port(self) -> None:
        domains = extract_url_domains("web_fetch", {"url": "localhost:3000/api"})
        assert domains == ("localhost",)

    def test_ip_address(self) -> None:
        domains = extract_url_domains("web_fetch", {"url": "http://192.168.1.1/api"})
        assert domains == ("192.168.1.1",)

    def test_net_fetch_extracts_hostname(self) -> None:
        """net_fetch (production permission) must also extract URL hostnames."""
        domains = extract_url_domains("net_fetch", {"url": "https://api.example.com/v1"})
        assert domains == ("api.example.com",)


class TestEvaluateToolCallDomainHitl:
    """Tests for evaluate_tool_call() with domain_hitl_enabled."""

    def test_domain_hitl_enabled_blocks_unknown(self) -> None:
        config = SecurityConfig(domain_hitl_enabled=True, network_allowlist=("example.com",))
        action, reason = evaluate_tool_call("web_fetch", {"url": "https://evil.com/x"}, config)
        assert action == PermissionAction.ASK
        assert "evil.com" in reason

    def test_domain_hitl_enabled_allows_known(self) -> None:
        config = SecurityConfig(domain_hitl_enabled=True, network_allowlist=("example.com",))
        action, _ = evaluate_tool_call("web_fetch", {"url": "https://example.com/x"}, config)
        assert action != PermissionAction.DENY

    def test_domain_hitl_disabled_no_check(self) -> None:
        config = SecurityConfig(domain_hitl_enabled=False, network_allowlist=("example.com",))
        _action, reason = evaluate_tool_call("web_fetch", {"url": "https://evil.com/x"}, config)
        assert "evil.com" not in reason

    def test_domain_hitl_non_url_tool_unaffected(self) -> None:
        config = SecurityConfig(domain_hitl_enabled=True, network_allowlist=())
        action, _ = evaluate_tool_call("file_read", {"path": "."}, config, workspace_root=os.getcwd())
        assert action == PermissionAction.ALLOW

    def test_net_fetch_domain_hitl_blocks_unknown(self) -> None:
        """Production path: web_fetch_tool resolves to net_fetch; domain HITL must still work."""
        config = SecurityConfig(domain_hitl_enabled=True, network_allowlist=("example.com",))
        action, reason = evaluate_tool_call("net_fetch", {"url": "https://evil.com/x"}, config)
        assert action == PermissionAction.ASK
        assert "evil.com" in reason

    def test_net_fetch_domain_hitl_allows_known(self) -> None:
        config = SecurityConfig(domain_hitl_enabled=True, network_allowlist=("example.com",))
        action, _ = evaluate_tool_call("net_fetch", {"url": "https://example.com/x"}, config)
        assert action != PermissionAction.DENY


class TestParseSecurityConfigDomainHitl:
    """Tests for parse_security_config() with domainHitlEnabled."""

    def test_parse_domain_hitl_enabled(self) -> None:
        config = parse_security_config({"domainHitlEnabled": True})
        assert config is not None
        assert config.domain_hitl_enabled is True

    def test_parse_domain_hitl_enabled_by_default(self) -> None:
        config = parse_security_config({"permissions": {}})
        assert config is not None
        assert config.domain_hitl_enabled is True

    def test_parse_domain_hitl_explicit_false(self) -> None:
        config = parse_security_config({"domainHitlEnabled": False})
        assert config is not None
        assert config.domain_hitl_enabled is False

    def test_parse_domain_hitl_with_allowlist(self) -> None:
        config = parse_security_config(
            {
                "domainHitlEnabled": True,
                "networkAllowlist": ["example.com", ".google.com"],
            }
        )
        assert config is not None
        assert config.domain_hitl_enabled is True
        assert config.network_allowlist == ("example.com", ".google.com")


class TestResolveTargetWebFetch:
    """Tests for _resolve_target() with web_fetch (hostname extraction)."""

    def test_web_fetch_extracts_hostname(self) -> None:
        target = _resolve_target("web_fetch", {"url": "https://api.example.com/v1"})
        assert target == "api.example.com"

    def test_web_fetch_no_url_returns_star(self) -> None:
        target = _resolve_target("web_fetch", {})
        assert target == "*"

    def test_web_fetch_bare_host(self) -> None:
        target = _resolve_target("web_fetch", {"url": "localhost:3000"})
        assert target == "localhost"

    def test_net_fetch_extracts_hostname(self) -> None:
        """net_fetch (production permission) must also extract hostname as target."""
        target = _resolve_target("net_fetch", {"url": "https://api.example.com/v1"})
        assert target == "api.example.com"


class TestSkillManageAndCronManagePermissions:
    """Tests for skill_manage and cron_manage permission rules across security profiles."""

    def test_default_ruleset_skill_manage_asks(self) -> None:
        """DEFAULT_RULESET: skill_manage should require human approval (ASK)."""
        config = SecurityConfig()
        action, _ = evaluate_tool_call("skill_manage", {}, config)
        assert action == PermissionAction.ASK

    def test_default_ruleset_cron_manage_asks(self) -> None:
        """DEFAULT_RULESET: cron_manage should require human approval (ASK)."""
        config = SecurityConfig()
        action, _ = evaluate_tool_call("cron_manage", {}, config)
        assert action == PermissionAction.ASK

    def test_readonly_profile_denies_skill_manage(self) -> None:
        """readonly() profile: skill_manage must be DENY (no side effects allowed)."""
        config = SecurityConfig.readonly()
        action, _ = evaluate_tool_call("skill_manage", {}, config)
        assert action == PermissionAction.DENY

    def test_readonly_profile_denies_cron_manage(self) -> None:
        """readonly() profile: cron_manage must be DENY (no side effects allowed)."""
        config = SecurityConfig.readonly()
        action, _ = evaluate_tool_call("cron_manage", {}, config)
        assert action == PermissionAction.DENY

    def test_workspace_profile_asks_skill_manage(self) -> None:
        """workspace() profile: skill_manage should require human approval (ASK)."""
        config = SecurityConfig.workspace(allowed_roots=("/home/user",))
        action, _ = evaluate_tool_call("skill_manage", {}, config)
        assert action == PermissionAction.ASK

    def test_workspace_profile_asks_cron_manage(self) -> None:
        """workspace() profile: cron_manage should require human approval (ASK)."""
        config = SecurityConfig.workspace(allowed_roots=("/home/user",))
        action, _ = evaluate_tool_call("cron_manage", {}, config)
        assert action == PermissionAction.ASK

    def test_remote_exposed_denies_skill_manage(self) -> None:
        """remote_exposed() profile: skill_manage must be DENY (untrusted environment)."""
        config = SecurityConfig.remote_exposed()
        action, _ = evaluate_tool_call("skill_manage", {}, config)
        assert action == PermissionAction.DENY

    def test_remote_exposed_denies_cron_manage(self) -> None:
        """remote_exposed() profile: cron_manage must be DENY (untrusted environment)."""
        config = SecurityConfig.remote_exposed()
        action, _ = evaluate_tool_call("cron_manage", {}, config)
        assert action == PermissionAction.DENY

    def test_full_access_allows_skill_manage(self) -> None:
        """full_access() profile: all operations allowed including skill_manage."""
        config = SecurityConfig.full_access()
        action, _ = evaluate_tool_call("skill_manage", {}, config)
        assert action == PermissionAction.ALLOW

    def test_user_override_allow_skill_manage(self) -> None:
        """User can explicitly ALLOW skill_manage via custom ruleset (last-match-wins)."""
        user_rules: PermissionRuleset = (PermissionRule("skill_manage", "*", PermissionAction.ALLOW),)
        config = SecurityConfig(ruleset=merge(DEFAULT_RULESET, user_rules))
        action, _ = evaluate_tool_call("skill_manage", {}, config)
        assert action == PermissionAction.ALLOW


class TestRiskClassificationIntegration:
    """Tests for risk-based auto-allow in evaluate_tool_call (fallback layer)."""

    def test_safe_command_auto_allowed(self) -> None:
        config = SecurityConfig()
        action, _ = evaluate_tool_call("shell_exec", {"command": "ls -la"}, config)
        assert action == PermissionAction.ALLOW

    def test_safe_pipeline_auto_allowed(self) -> None:
        config = SecurityConfig()
        action, _ = evaluate_tool_call("shell_exec", {"command": "cat file | grep pattern"}, config)
        assert action == PermissionAction.ALLOW

    def test_unknown_command_still_asks(self) -> None:
        config = SecurityConfig()
        action, _ = evaluate_tool_call("shell_exec", {"command": "rm file.txt"}, config)
        assert action == PermissionAction.ASK

    def test_redirect_not_auto_allowed(self) -> None:
        config = SecurityConfig()
        action, _ = evaluate_tool_call("shell_exec", {"command": "echo hello > file.txt"}, config)
        assert action == PermissionAction.ASK

    def test_dangerous_command_still_denied(self) -> None:
        config = SecurityConfig()
        action, _ = evaluate_tool_call("shell_exec", {"command": "rm -rf /"}, config)
        assert action in (PermissionAction.DENY, PermissionAction.ASK)

    def test_user_deny_overrides_risk_classification(self) -> None:
        config = SecurityConfig(ruleset=(PermissionRule("shell_exec", "*", PermissionAction.DENY),))
        action, _ = evaluate_tool_call("shell_exec", {"command": "ls"}, config)
        assert action == PermissionAction.DENY

    def test_user_allow_still_works(self) -> None:
        config = SecurityConfig(ruleset=(PermissionRule("shell_exec", "*", PermissionAction.ALLOW),))
        action, _ = evaluate_tool_call("shell_exec", {"command": "rm file.txt"}, config)
        assert action == PermissionAction.ALLOW

    def test_non_shell_permission_unaffected(self) -> None:
        config = SecurityConfig()
        action, _ = evaluate_tool_call("file_read", {"path": "."}, config, workspace_root=os.getcwd())
        assert action == PermissionAction.ALLOW

    def test_git_read_only_auto_allowed(self) -> None:
        """Git read-only commands with valid flags should be auto-allowed via risk classifier."""
        config = SecurityConfig()
        action, _ = evaluate_tool_call("shell_exec", {"command": "git status -s"}, config)
        assert action == PermissionAction.ALLOW

    def test_git_log_with_flags_auto_allowed(self) -> None:
        config = SecurityConfig()
        action, _ = evaluate_tool_call("shell_exec", {"command": "git log --oneline -n 10"}, config)
        assert action == PermissionAction.ALLOW

    def test_git_diff_auto_allowed(self) -> None:
        config = SecurityConfig()
        action, _ = evaluate_tool_call("shell_exec", {"command": "git diff --stat"}, config)
        assert action == PermissionAction.ALLOW

    def test_git_push_not_auto_allowed(self) -> None:
        """Write operations should remain ASK."""
        config = SecurityConfig()
        action, _ = evaluate_tool_call("shell_exec", {"command": "git push origin main"}, config)
        assert action == PermissionAction.ASK

    def test_git_commit_not_auto_allowed(self) -> None:
        config = SecurityConfig()
        action, _ = evaluate_tool_call("shell_exec", {"command": "git commit -m 'test'"}, config)
        assert action == PermissionAction.ASK

    def test_git_unknown_flag_not_auto_allowed(self) -> None:
        """Git commands with unknown flags should remain ASK."""
        config = SecurityConfig()
        action, _ = evaluate_tool_call("shell_exec", {"command": "git diff --output=pwned.txt"}, config)
        assert action == PermissionAction.ASK

    def test_code_interpreter_git_status_auto_allowed(self) -> None:
        """bash_code_execute_tool maps to code_interpreter; risk classifier should still apply."""
        config = SecurityConfig()
        action, _ = evaluate_tool_call("code_interpreter", {"command": "git status"}, config)
        assert action == PermissionAction.ALLOW

    def test_code_interpreter_ls_auto_allowed(self) -> None:
        config = SecurityConfig()
        action, _ = evaluate_tool_call("code_interpreter", {"command": "ls -la"}, config)
        assert action == PermissionAction.ALLOW

    def test_code_interpreter_git_push_still_ask(self) -> None:
        config = SecurityConfig()
        action, _ = evaluate_tool_call("code_interpreter", {"command": "git push"}, config)
        assert action == PermissionAction.ASK

    def test_code_interpreter_echo_auto_allowed(self) -> None:
        config = SecurityConfig()
        action, _ = evaluate_tool_call("code_interpreter", {"command": "echo hello"}, config)
        assert action == PermissionAction.ALLOW
