"""Tests for security.channel_presets — per-channel security configuration."""

from __future__ import annotations

from myrm_agent_harness.agent.security.channel_presets import (
    CHANNEL_PRESETS,
    ChannelType,
    build_channel_security_config,
    get_local_browser_relaxation,
    resolve_channel_type,
)
from myrm_agent_harness.agent.security.types import PermissionAction


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

    def test_unknown_is_web_chat(self) -> None:
        assert resolve_channel_type("unknown_channel") == ChannelType.WEB_CHAT


class TestChannelPresets:
    def test_all_channel_types_have_presets(self) -> None:
        for ct in ChannelType:
            assert ct in CHANNEL_PRESETS

    def test_im_blocks_browser(self) -> None:
        preset = CHANNEL_PRESETS[ChannelType.IM]
        negatives = [c for c in preset.capabilities if c.permission.startswith("!")]
        assert any("browser" in c.permission for c in negatives)

    def test_cron_allows_shell(self) -> None:
        preset = CHANNEL_PRESETS[ChannelType.CRON]
        shell_rules = [r for r in preset.ruleset if r.permission == "shell_exec"]
        assert any(r.action == PermissionAction.ALLOW for r in shell_rules)


class TestLocalBrowserRelaxation:
    def test_returns_rules(self) -> None:
        rules = get_local_browser_relaxation()
        assert len(rules) > 0

    def test_allows_localhost(self) -> None:
        rules = get_local_browser_relaxation()
        localhost_rules = [r for r in rules if "localhost" in r.pattern]
        assert any(r.action == PermissionAction.ALLOW for r in localhost_rules)

    def test_covers_all_rfc1918_172_subnets(self) -> None:
        rules = get_local_browser_relaxation()
        nav_patterns = {r.pattern for r in rules if r.permission == "browser_navigate"}
        for i in range(16, 32):
            assert f"172.{i}.*" in nav_patterns

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

    def test_cron_with_declared_capabilities(self) -> None:
        config = build_channel_security_config("cron", declared_capabilities=("shell_exec", "file_read"))
        caps_perms = {c.permission for c in config.capabilities}
        assert "shell_exec" in caps_perms
        assert "file_read" in caps_perms

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
