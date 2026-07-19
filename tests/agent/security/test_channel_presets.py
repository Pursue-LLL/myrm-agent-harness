"""Tests for security.channel_presets — per-channel security configuration."""

from __future__ import annotations

from myrm_agent_harness.agent.security.channel_presets import (
    CHANNEL_PRESETS,
    ChannelType,
    build_channel_security_config,
    get_local_browser_relaxation,
    resolve_channel_type,
)
from myrm_agent_harness.agent.security.engine import evaluate_tool_call
from myrm_agent_harness.agent.security.types import (
    PermissionAction,
    PrivacyPolicy,
)


class TestResolveChannelType:
    def test_telegram_is_im(self) -> None:
        assert resolve_channel_type("telegram") == ChannelType.IM

    def test_slack_is_im(self) -> None:
        assert resolve_channel_type("slack") == ChannelType.IM

    def test_feishu_is_im(self) -> None:
        assert resolve_channel_type("feishu") == ChannelType.IM

    def test_cron_is_cron(self) -> None:
        assert resolve_channel_type("cron") == ChannelType.CRON

    def test_web_chat_default(self) -> None:
        assert resolve_channel_type("web_chat") == ChannelType.WEB_CHAT

    def test_unknown_defaults_to_im(self) -> None:
        """Unknown channels default to IM (least privilege) for defense-in-depth."""
        assert resolve_channel_type("unknown_channel") == ChannelType.IM

    def test_empty_string_defaults_to_im(self) -> None:
        """Empty channel name from misconfiguration defaults to IM."""
        assert resolve_channel_type("") == ChannelType.IM

    def test_case_sensitive_web_chat_uppercase_defaults_to_im(self) -> None:
        """Channel name matching is case-sensitive; 'WEB_CHAT' != 'web_chat'."""
        assert resolve_channel_type("WEB_CHAT") == ChannelType.IM

    def test_case_sensitive_cron_uppercase_defaults_to_im(self) -> None:
        """'CRON' is not 'cron' — strict lowercase match required."""
        assert resolve_channel_type("CRON") == ChannelType.IM

    def test_qq_is_im(self) -> None:
        assert resolve_channel_type("qq") == ChannelType.IM

    def test_onebot_is_im(self) -> None:
        assert resolve_channel_type("onebot") == ChannelType.IM

    def test_wechat_is_im(self) -> None:
        assert resolve_channel_type("wechat") == ChannelType.IM

    def test_wechat_official_is_im(self) -> None:
        assert resolve_channel_type("wechat_official") == ChannelType.IM

    def test_wecom_aibot_is_im(self) -> None:
        assert resolve_channel_type("wecom_aibot") == ChannelType.IM

    def test_line_is_im(self) -> None:
        assert resolve_channel_type("line") == ChannelType.IM

    def test_mattermost_is_im(self) -> None:
        assert resolve_channel_type("mattermost") == ChannelType.IM

    def test_signal_is_im(self) -> None:
        assert resolve_channel_type("signal") == ChannelType.IM

    def test_email_is_im(self) -> None:
        assert resolve_channel_type("email") == ChannelType.IM

    def test_github_is_im(self) -> None:
        assert resolve_channel_type("github") == ChannelType.IM

    def test_sms_is_im(self) -> None:
        assert resolve_channel_type("sms") == ChannelType.IM

    def test_voice_is_im(self) -> None:
        assert resolve_channel_type("voice") == ChannelType.IM


class TestChannelPresets:
    def test_all_channel_types_have_presets(self) -> None:
        for ct in ChannelType:
            assert ct in CHANNEL_PRESETS

    def test_im_blocks_browser(self) -> None:
        preset = CHANNEL_PRESETS[ChannelType.IM]
        negatives = [c for c in preset.capabilities if c.permission.startswith("!")]
        assert any("browser" in c.permission for c in negatives)

    def test_im_blocks_desktop(self) -> None:
        preset = CHANNEL_PRESETS[ChannelType.IM]
        negatives = [c for c in preset.capabilities if c.permission.startswith("!")]
        assert any("desktop" in c.permission for c in negatives)

    def test_im_preset_denies_shell(self) -> None:
        """IM preset must have shell_exec DENY rule."""
        preset = CHANNEL_PRESETS[ChannelType.IM]
        shell_rules = [r for r in preset.ruleset if r.permission == "shell_exec"]
        assert any(r.action == PermissionAction.DENY for r in shell_rules)

    def test_im_preset_asks_code_interpreter(self) -> None:
        """IM preset must require approval for code_interpreter."""
        preset = CHANNEL_PRESETS[ChannelType.IM]
        ci_rules = [r for r in preset.ruleset if r.permission == "code_interpreter"]
        assert any(r.action == PermissionAction.ASK for r in ci_rules)

    def test_im_preset_asks_mcp_invoke(self) -> None:
        """IM preset must require approval for mcp_invoke."""
        preset = CHANNEL_PRESETS[ChannelType.IM]
        mcp_rules = [r for r in preset.ruleset if r.permission == "mcp_invoke"]
        assert any(r.action == PermissionAction.ASK for r in mcp_rules)

    def test_web_chat_preset_has_empty_ruleset(self) -> None:
        """WEB_CHAT preset inherits defaults without additional restrictions."""
        preset = CHANNEL_PRESETS[ChannelType.WEB_CHAT]
        assert preset.ruleset == ()

    def test_cron_allows_shell(self) -> None:
        preset = CHANNEL_PRESETS[ChannelType.CRON]
        shell_rules = [r for r in preset.ruleset if r.permission == "shell_exec"]
        assert any(r.action == PermissionAction.ALLOW for r in shell_rules)

    def test_cron_allows_code_interpreter(self) -> None:
        """Cron jobs run unattended — code_interpreter is auto-allowed."""
        preset = CHANNEL_PRESETS[ChannelType.CRON]
        ci_rules = [r for r in preset.ruleset if r.permission == "code_interpreter"]
        assert any(r.action == PermissionAction.ALLOW for r in ci_rules)

    def test_cron_allows_mcp_invoke(self) -> None:
        """Cron jobs run unattended — mcp_invoke is auto-allowed."""
        preset = CHANNEL_PRESETS[ChannelType.CRON]
        mcp_rules = [r for r in preset.ruleset if r.permission == "mcp_invoke"]
        assert any(r.action == PermissionAction.ALLOW for r in mcp_rules)

    def test_cron_denies_desktop_capture(self) -> None:
        preset = CHANNEL_PRESETS[ChannelType.CRON]
        rules = [r for r in preset.ruleset if r.permission == "desktop_capture"]
        assert len(rules) == 1
        assert rules[0].action == PermissionAction.DENY

    def test_cron_denies_desktop_control(self) -> None:
        preset = CHANNEL_PRESETS[ChannelType.CRON]
        rules = [r for r in preset.ruleset if r.permission == "desktop_control"]
        assert len(rules) == 1
        assert rules[0].action == PermissionAction.DENY


class TestLocalBrowserRelaxation:
    def test_returns_rules(self) -> None:
        rules = get_local_browser_relaxation()
        assert len(rules) > 0

    def test_allows_localhost(self) -> None:
        rules = get_local_browser_relaxation()
        localhost_rules = [r for r in rules if "localhost" in r.pattern]
        assert any(r.action == PermissionAction.ALLOW for r in localhost_rules)

    def test_allows_loopback_ip(self) -> None:
        """127.0.0.1 must be allowed for local mode."""
        rules = get_local_browser_relaxation()
        loopback_rules = [r for r in rules if "127.0.0.1" in r.pattern]
        assert any(r.action == PermissionAction.ALLOW for r in loopback_rules)

    def test_allows_zero_bind(self) -> None:
        """0.0.0.0 binding must be allowed for local dev servers."""
        rules = get_local_browser_relaxation()
        zero_rules = [r for r in rules if "0.0.0.0" in r.pattern]
        assert any(r.action == PermissionAction.ALLOW for r in zero_rules)

    def test_allows_class_c_private(self) -> None:
        """192.168.* must be allowed for local network access."""
        rules = get_local_browser_relaxation()
        nav_patterns = {r.pattern for r in rules if r.permission == "browser_navigate"}
        assert "192.168.*" in nav_patterns

    def test_allows_class_a_private(self) -> None:
        """10.* must be allowed for local network access."""
        rules = get_local_browser_relaxation()
        nav_patterns = {r.pattern for r in rules if r.permission == "browser_navigate"}
        assert "10.*" in nav_patterns

    def test_covers_all_rfc1918_172_subnets(self) -> None:
        rules = get_local_browser_relaxation()
        nav_patterns = {r.pattern for r in rules if r.permission == "browser_navigate"}
        for i in range(16, 32):
            assert f"172.{i}.*" in nav_patterns

    def test_allows_browser_fill(self) -> None:
        """Local mode allows browser_fill for form automation."""
        rules = get_local_browser_relaxation()
        fill_rules = [r for r in rules if r.permission == "browser_fill"]
        assert any(r.action == PermissionAction.ALLOW for r in fill_rules)

    def test_allows_browser_upload_download_session(self) -> None:
        rules = get_local_browser_relaxation()
        perms = {r.permission for r in rules if r.action == PermissionAction.ALLOW}
        assert "browser_upload" in perms
        assert "browser_download" in perms
        assert "browser_session" in perms


class TestBuildChannelSecurityConfig:
    def test_web_chat_default(self) -> None:
        config = build_channel_security_config("web_chat")
        assert config.approval_timeout_seconds == 120

    def test_im_channel(self) -> None:
        config = build_channel_security_config("telegram")
        assert config is not None

    def test_im_channel_denies_browser_navigate(self) -> None:
        """IM channels must deny browser_navigate through the full security chain."""
        config = build_channel_security_config("telegram")
        action, _ = evaluate_tool_call("browser_navigate", {"url": "https://example.com"}, config)
        assert action == PermissionAction.DENY

    def test_im_channel_denies_desktop_control(self) -> None:
        """IM channels must deny desktop_control through the capability fence."""
        config = build_channel_security_config("telegram")
        action, reason = evaluate_tool_call("desktop_control", {}, config)
        assert action == PermissionAction.DENY
        assert "Capability not granted" in reason

    def test_im_channel_denies_desktop_capture(self) -> None:
        """IM channels must deny desktop_capture through the capability fence."""
        config = build_channel_security_config("telegram")
        action, reason = evaluate_tool_call("desktop_capture", {}, config)
        assert action == PermissionAction.DENY
        assert "Capability not granted" in reason

    def test_cron_channel_denies_desktop_control(self) -> None:
        config = build_channel_security_config("cron", declared_capabilities=("shell_exec", "file_read"))
        action, _ = evaluate_tool_call("desktop_control", {}, config)
        assert action == PermissionAction.DENY

    def test_cron_channel_denies_desktop_capture(self) -> None:
        config = build_channel_security_config("cron", declared_capabilities=("shell_exec", "file_read"))
        action, _ = evaluate_tool_call("desktop_capture", {}, config)
        assert action == PermissionAction.DENY

    def test_cron_with_declared_capabilities(self) -> None:
        config = build_channel_security_config("cron", declared_capabilities=("shell_exec", "file_read"))
        caps_perms = {c.permission for c in config.capabilities}
        assert "shell_exec" in caps_perms
        assert "file_read" in caps_perms

    def test_cron_without_declared_capabilities_gets_empty_set(self) -> None:
        """Cron with no declared_capabilities produces an empty CapabilitySet."""
        config = build_channel_security_config("cron")
        assert len(config.capabilities) == 0

    def test_cron_with_allowed_roots(self) -> None:
        config = build_channel_security_config("cron", declared_allowed_roots=("/tmp/jobs",))
        assert "/tmp/jobs" in config.path_policy.allowed_roots

    def test_web_chat_with_declared_allowed_roots(self) -> None:
        config = build_channel_security_config("web_chat", declared_allowed_roots=("/home/user/projects",))
        assert "/home/user/projects" in config.path_policy.allowed_roots

    def test_local_mode_relaxes_browser(self) -> None:
        config = build_channel_security_config("web_chat", local_mode=True)
        localhost_rules = [r for r in config.ruleset if "localhost" in r.pattern]
        assert any(r.action == PermissionAction.ALLOW for r in localhost_rules)

    def test_local_mode_allows_upload_download(self) -> None:
        config = build_channel_security_config("web_chat", local_mode=True)
        upload_rules = [r for r in config.ruleset if r.permission == "browser_upload"]
        assert any(r.action == PermissionAction.ALLOW for r in upload_rules)

    def test_no_user_no_agent_config_uses_defaults(self) -> None:
        """build without user/agent config uses preset defaults."""
        config = build_channel_security_config("web_chat")
        assert config.approval_timeout_seconds == 120
        assert config.approval_timeout_behavior == "deny"
        assert config.network_allowlist == ()

    def test_privacy_policy_passthrough(self) -> None:
        """privacy_policy parameter is correctly attached to the result."""
        pp = PrivacyPolicy(enabled=True)
        config = build_channel_security_config("web_chat", privacy_policy=pp)
        assert config.privacy_policy.enabled is True

    def test_user_config_applied(self) -> None:
        config = build_channel_security_config(
            "web_chat",
            user_config_raw={
                "approvalTimeoutSeconds": 60,
                "permissions": {"shell_exec": "deny"},
            },
        )
        assert config.approval_timeout_seconds == 60

    def test_agent_config_restricts_capabilities(self) -> None:
        config = build_channel_security_config(
            "web_chat",
            user_config_raw={
                "capabilities": ["shell_exec", "file_read"],
            },
            agent_security_raw={
                "capabilities": ["file_read"],
            },
        )
        caps_perms = {c.permission for c in config.capabilities}
        assert "file_read" in caps_perms

    def test_agent_timeout_overrides_user(self) -> None:
        config = build_channel_security_config(
            "web_chat",
            user_config_raw={"approvalTimeoutSeconds": 60},
            agent_security_raw={"approvalTimeoutSeconds": 30},
        )
        assert config.approval_timeout_seconds == 30

    def test_qq_channel_denies_shell(self) -> None:
        """QQ channel must deny shell_exec via IM preset."""
        config = build_channel_security_config("qq")
        action, _ = evaluate_tool_call("shell_exec", {"command": "echo hello"}, config)
        assert action == PermissionAction.DENY

    def test_wechat_channel_denies_shell(self) -> None:
        config = build_channel_security_config("wechat")
        action, _ = evaluate_tool_call("shell_exec", {"command": "ls"}, config)
        assert action == PermissionAction.DENY

    def test_onebot_channel_denies_shell(self) -> None:
        config = build_channel_security_config("onebot")
        action, _ = evaluate_tool_call("shell_exec", {"command": "pwd"}, config)
        assert action == PermissionAction.DENY

    def test_im_code_interpreter_requires_approval(self) -> None:
        """IM channels must ASK for code_interpreter through the full chain."""
        config = build_channel_security_config("telegram")
        action, _ = evaluate_tool_call("code_interpreter", {"code": "print(1)"}, config)
        assert action == PermissionAction.ASK

    def test_im_mcp_invoke_requires_approval(self) -> None:
        """IM channels must ASK for mcp_invoke through the full chain."""
        config = build_channel_security_config("slack")
        action, _ = evaluate_tool_call("mcp_invoke", {"server": "test"}, config)
        assert action == PermissionAction.ASK

    def test_channel_preset_overrides_user_allow(self) -> None:
        """Channel preset rules cannot be bypassed by user config — last-match-wins."""
        config = build_channel_security_config(
            "telegram",
            user_config_raw={"permissions": {"shell_exec": "allow"}},
        )
        action, _ = evaluate_tool_call("shell_exec", {"command": "rm -rf /"}, config)
        assert action == PermissionAction.DENY
