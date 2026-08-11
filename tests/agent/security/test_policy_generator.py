"""Tests for security.policy_generator module.

Covers: prompts, parser, validator, explainer.
"""

import pytest

from myrm_agent_harness.agent.security.policy_generator import (
    PolicyParseError,
    WarningSeverity,
    build_messages,
    explain_policy,
    parse_policy_response,
    validate_generated_policy,
)


class TestBuildMessages:
    """Tests for build_messages (prompts.py)."""

    def test_basic_message_structure(self) -> None:
        msgs = build_messages("禁止执行rm命令")
        assert len(msgs) == 2
        assert msgs[0]["role"] == "system"
        assert msgs[1]["role"] == "user"
        assert "禁止执行rm命令" in msgs[1]["content"]

    def test_with_current_config(self) -> None:
        config = {"permissions": {"shell_exec": "ask"}, "networkAllowlist": ["github.com"]}
        msgs = build_messages("add npm domains", current_config=config)
        assert "Current configuration context" in msgs[1]["content"]
        assert "github.com" in msgs[1]["content"]

    def test_with_command_denylist_in_context(self) -> None:
        config = {"commandDenylist": ["rm -rf *"], "networkBlocklist": ["malware.com"]}
        msgs = build_messages("update policy", current_config=config)
        assert "Command denylist" in msgs[1]["content"]
        assert "rm -rf *" in msgs[1]["content"]
        assert "Blocked domains" in msgs[1]["content"]
        assert "malware.com" in msgs[1]["content"]

    def test_without_current_config(self) -> None:
        msgs = build_messages("block all commands")
        assert "Current configuration context" not in msgs[1]["content"]

    def test_empty_config_no_context_added(self) -> None:
        msgs = build_messages("test", current_config={})
        assert "Current configuration context" not in msgs[1]["content"]
        assert msgs[1]["content"] == "test"


class TestParsePolicy:
    """Tests for parse_policy_response (parser.py)."""

    def test_clean_json(self) -> None:
        raw = '{"permissions": {"shell_exec": "deny"}, "networkAllowlist": ["github.com"]}'
        result = parse_policy_response(raw)
        assert result["permissions"] == {"shell_exec": "deny"}
        assert result["networkAllowlist"] == ["github.com"]

    def test_markdown_code_block(self) -> None:
        raw = '```json\n{"permissions": {"file_read": "allow"}}\n```'
        result = parse_policy_response(raw)
        assert result["permissions"] == {"file_read": "allow"}

    def test_noisy_text_with_json(self) -> None:
        raw = 'Here is the config:\n{"permissions": {"shell_exec": "deny"}}\nHope this helps!'
        result = parse_policy_response(raw)
        assert result["permissions"] == {"shell_exec": "deny"}

    def test_invalid_json_raises(self) -> None:
        with pytest.raises(PolicyParseError):
            parse_policy_response("this is not json at all")

    def test_non_dict_raises(self) -> None:
        with pytest.raises(PolicyParseError):
            parse_policy_response("[1, 2, 3]")

    def test_filters_unknown_keys(self) -> None:
        raw = '{"permissions": {"shell_exec": "deny"}, "unknownKey": true}'
        result = parse_policy_response(raw)
        assert "unknownKey" not in result
        assert "permissions" in result

    def test_normalizes_actions(self) -> None:
        raw = '{"permissions": {"shell_exec": "invalid_action", "file_read": "allow"}}'
        result = parse_policy_response(raw)
        perms = result["permissions"]
        assert "file_read" in perms
        assert "shell_exec" not in perms

    def test_normalizes_network_allowlist(self) -> None:
        raw = '{"networkAllowlist": ["GitHub.com", "  API.OPENAI.COM  "]}'
        result = parse_policy_response(raw)
        assert result["networkAllowlist"] == ["github.com", "api.openai.com"]

    def test_normalizes_privacy_policy(self) -> None:
        raw = '{"privacyPolicy": {"enabled": true, "s2Action": "redact", "s3Action": "block"}}'
        result = parse_policy_response(raw)
        pp = result["privacyPolicy"]
        assert pp["enabled"] is True
        assert pp["s2Action"] == "redact"
        assert pp["s3Action"] == "block"

    def test_invalid_timeout_removed(self) -> None:
        raw = '{"approvalTimeoutSeconds": 99999}'
        result = parse_policy_response(raw)
        assert "approvalTimeoutSeconds" not in result

    def test_valid_timeout_kept(self) -> None:
        raw = '{"approvalTimeoutSeconds": 120}'
        result = parse_policy_response(raw)
        assert result["approvalTimeoutSeconds"] == 120

    def test_path_policy_normalization(self) -> None:
        raw = '{"pathPolicy": {"allowedRoots": ["~/projects", "/tmp"], "forbiddenPaths": ["~/.ssh"]}}'
        result = parse_policy_response(raw)
        pp = result["pathPolicy"]
        assert pp["allowedRoots"] == ["~/projects", "/tmp"]
        assert pp["forbiddenPaths"] == ["~/.ssh"]

    def test_nested_permissions_with_patterns(self) -> None:
        raw = '{"permissions": {"shell_exec": {"rm *": "deny", "git *": "allow"}}}'
        result = parse_policy_response(raw)
        perms = result["permissions"]
        assert perms["shell_exec"] == {"rm *": "deny", "git *": "allow"}

    def test_parses_command_denylist(self) -> None:
        raw = '{"commandDenylist": ["rm -rf *", "git push --force*"]}'
        result = parse_policy_response(raw)
        assert result["commandDenylist"] == ["rm -rf *", "git push --force*"]

    def test_normalizes_command_denylist_strips_whitespace(self) -> None:
        raw = '{"commandDenylist": ["  rm -rf * ", "", "git push --force*"]}'
        result = parse_policy_response(raw)
        assert result["commandDenylist"] == ["rm -rf *", "git push --force*"]

    def test_parses_network_blocklist(self) -> None:
        raw = '{"networkBlocklist": ["Malware.COM", "*.phishing.NET"]}'
        result = parse_policy_response(raw)
        assert result["networkBlocklist"] == ["malware.com", "*.phishing.net"]

    def test_invalid_command_denylist_type_removed(self) -> None:
        raw = '{"commandDenylist": "not a list"}'
        result = parse_policy_response(raw)
        assert "commandDenylist" not in result

    def test_invalid_network_blocklist_type_removed(self) -> None:
        raw = '{"networkBlocklist": "not a list"}'
        result = parse_policy_response(raw)
        assert "networkBlocklist" not in result

    def test_multiline_json_values(self) -> None:
        """Values containing raw newlines (reasoning-model artifacts) must parse."""
        raw = (
            '{"permissions": {"shell_exec": "deny"}, '
            '"commandDenylist": ["rm -rf *", "git push\n--force"]}'
        )
        result = parse_policy_response(raw)
        assert result["permissions"] == {"shell_exec": "deny"}
        assert result["commandDenylist"] == ["rm -rf *", "git push\n--force"]

    def test_example_object_precedes_real(self) -> None:
        """When a format example precedes the real config, the last object wins."""
        raw = (
            'Example: {"permissions": {"file_read": "allow"}}\n'
            'Real config: {"permissions": {"shell_exec": "deny"}}'
        )
        result = parse_policy_response(raw)
        assert result["permissions"] == {"shell_exec": "deny"}
        assert "file_read" not in result["permissions"]


class TestValidatePolicy:
    """Tests for validate_generated_policy (validator.py)."""

    def test_empty_policy_valid(self) -> None:
        is_valid, warnings = validate_generated_policy({})
        assert is_valid
        assert len(warnings) == 1
        assert warnings[0].severity == WarningSeverity.WARNING

    def test_dangerous_shell_exec_allow(self) -> None:
        config = {"permissions": {"shell_exec": "allow"}}
        is_valid, warnings = validate_generated_policy(config)
        assert not is_valid
        assert any(w.severity == WarningSeverity.DANGER for w in warnings)

    def test_safe_permissions_valid(self) -> None:
        config = {"permissions": {"file_read": "allow", "shell_exec": "ask"}}
        is_valid, warnings = validate_generated_policy(config)
        assert is_valid
        assert len(warnings) == 0

    def test_root_path_danger(self) -> None:
        config = {"pathPolicy": {"allowedRoots": ["/"]}}
        is_valid, _warnings = validate_generated_policy(config)
        assert not is_valid

    def test_system_path_warning(self) -> None:
        config = {"pathPolicy": {"allowedRoots": ["/etc/nginx"]}}
        is_valid, warnings = validate_generated_policy(config)
        assert is_valid
        assert any(w.severity == WarningSeverity.WARNING for w in warnings)

    def test_wildcard_network_danger(self) -> None:
        config = {"networkAllowlist": ["*"]}
        is_valid, _warnings = validate_generated_policy(config)
        assert not is_valid

    def test_normal_network_valid(self) -> None:
        config = {"networkAllowlist": ["github.com", "*.npm.org"]}
        is_valid, _warnings = validate_generated_policy(config)
        assert is_valid

    def test_s3_warn_warning(self) -> None:
        config = {"privacyPolicy": {"enabled": True, "s3Action": "warn"}}
        is_valid, warnings = validate_generated_policy(config)
        assert is_valid
        assert any("S3" in w.message for w in warnings)

    def test_conflict_detection(self) -> None:
        generated = {"permissions": {"shell_exec": "allow"}}
        current = {"permissions": {"shell_exec": "deny"}}
        _is_valid, warnings = validate_generated_policy(generated, current)
        assert any("Overriding" in w.message for w in warnings)

    def test_nested_wildcard_danger(self) -> None:
        config = {"permissions": {"shell_exec": {"*": "allow"}}}
        is_valid, _warnings = validate_generated_policy(config)
        assert not is_valid

    def test_command_denylist_wildcard_warning(self) -> None:
        config = {"commandDenylist": ["*"]}
        is_valid, warnings = validate_generated_policy(config)
        assert is_valid
        assert any(w.field == "commandDenylist" and w.severity == WarningSeverity.WARNING for w in warnings)

    def test_command_denylist_normal_patterns_valid(self) -> None:
        config = {"commandDenylist": ["rm -rf *", "git push --force*"]}
        is_valid, warnings = validate_generated_policy(config)
        assert is_valid
        assert len(warnings) == 0


class TestExplainPolicy:
    """Tests for explain_policy (explainer.py)."""

    def test_empty_config_zh(self) -> None:
        result = explain_policy({}, locale="zh")
        assert result == "无变更"

    def test_empty_config_en(self) -> None:
        result = explain_policy({}, locale="en")
        assert result == "No changes"

    def test_permissions_zh(self) -> None:
        config = {"permissions": {"shell_exec": "deny", "file_read": "allow"}}
        result = explain_policy(config, locale="zh")
        assert "Shell 命令执行" in result
        assert "禁止" in result
        assert "允许" in result

    def test_permissions_en(self) -> None:
        config = {"permissions": {"shell_exec": "deny"}}
        result = explain_policy(config, locale="en")
        assert "Shell command execution" in result
        assert "Deny" in result

    def test_path_policy(self) -> None:
        config = {"pathPolicy": {"allowedRoots": ["~/projects"]}}
        result = explain_policy(config, locale="zh")
        assert "~/projects" in result
        assert "路径访问" in result

    def test_privacy_policy(self) -> None:
        config = {"privacyPolicy": {"enabled": True, "s2Action": "pseudonymize", "s3Action": "redact"}}
        result = explain_policy(config, locale="zh")
        assert "可逆脱敏" in result
        assert "不可逆脱敏" in result

    def test_network_allowlist(self) -> None:
        config = {"networkAllowlist": ["github.com"]}
        result = explain_policy(config, locale="en")
        assert "github.com" in result
        assert "Trusted domains" in result

    def test_domain_hitl_enabled(self) -> None:
        config = {"domainHitlEnabled": True}
        result = explain_policy(config, locale="zh")
        assert "未知域名需审批" in result

    def test_domain_hitl_disabled(self) -> None:
        config = {"domainHitlEnabled": False}
        result = explain_policy(config, locale="en")
        assert "auto-allowed" in result

    def test_timeout_settings(self) -> None:
        config = {"approvalTimeoutSeconds": 60, "approvalTimeoutBehavior": "deny"}
        result = explain_policy(config, locale="zh")
        assert "60秒" in result
        assert "超时后拒绝" in result

    def test_pattern_permissions(self) -> None:
        config = {"permissions": {"shell_exec": {"rm *": "deny", "git *": "allow"}}}
        result = explain_policy(config, locale="zh")
        assert "[rm *]" in result
        assert "[git *]" in result

    def test_command_denylist_zh(self) -> None:
        config = {"commandDenylist": ["rm -rf *", "git push --force*"]}
        result = explain_policy(config, locale="zh")
        assert "永久禁止命令" in result
        assert "rm -rf *" in result

    def test_command_denylist_en(self) -> None:
        config = {"commandDenylist": ["rm -rf *"]}
        result = explain_policy(config, locale="en")
        assert "Permanently blocked commands" in result
        assert "rm -rf *" in result

    def test_network_blocklist_zh(self) -> None:
        config = {"networkBlocklist": ["malware.com"]}
        result = explain_policy(config, locale="zh")
        assert "封锁域名" in result
        assert "malware.com" in result

    def test_network_blocklist_en(self) -> None:
        config = {"networkBlocklist": ["*.phishing.net"]}
        result = explain_policy(config, locale="en")
        assert "Blocked domains" in result
        assert "*.phishing.net" in result
