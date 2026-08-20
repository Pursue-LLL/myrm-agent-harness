"""Tests for SecurityConfig factory methods and PathPolicy.workspace_label."""

from __future__ import annotations

from myrm_agent_harness.agent.security.types import (
    Capability,
    PathPolicy,
    PermissionAction,
    SecurityConfig,
    access_roots_from_paths,
)


class TestSecurityConfigReadonly:
    """Tests for SecurityConfig.readonly() factory method."""

    def test_readonly_creates_config(self) -> None:
        config = SecurityConfig.readonly()
        assert isinstance(config, SecurityConfig)

    def test_readonly_yolo_disabled(self) -> None:
        config = SecurityConfig.readonly()
        assert config.yolo_mode_enabled is False

    def test_readonly_auto_mode_enabled_by_default(self) -> None:
        config = SecurityConfig.readonly()
        assert config.auto_mode_enabled is True

    def test_readonly_denies_file_write(self) -> None:
        config = SecurityConfig.readonly()
        write_rules = [r for r in config.ruleset if r.permission == "file_write"]
        assert len(write_rules) == 1
        assert write_rules[0].action == PermissionAction.DENY

    def test_readonly_denies_file_edit(self) -> None:
        config = SecurityConfig.readonly()
        edit_rules = [r for r in config.ruleset if r.permission == "file_edit"]
        assert len(edit_rules) == 1
        assert edit_rules[0].action == PermissionAction.DENY

    def test_readonly_denies_file_delete(self) -> None:
        config = SecurityConfig.readonly()
        delete_rules = [r for r in config.ruleset if r.permission == "file_delete"]
        assert len(delete_rules) == 1
        assert delete_rules[0].action == PermissionAction.DENY

    def test_readonly_denies_shell_exec(self) -> None:
        config = SecurityConfig.readonly()
        shell_rules = [r for r in config.ruleset if r.permission == "shell_exec"]
        assert len(shell_rules) == 1
        assert shell_rules[0].action == PermissionAction.DENY

    def test_readonly_denies_code_interpreter(self) -> None:
        config = SecurityConfig.readonly()
        ci_rules = [r for r in config.ruleset if r.permission == "code_interpreter"]
        assert len(ci_rules) == 1
        assert ci_rules[0].action == PermissionAction.DENY

    def test_readonly_denies_browser_evaluate(self) -> None:
        config = SecurityConfig.readonly()
        be_rules = [r for r in config.ruleset if r.permission == "browser_evaluate"]
        assert len(be_rules) == 1
        assert be_rules[0].action == PermissionAction.DENY

    def test_readonly_denies_browser_fill(self) -> None:
        config = SecurityConfig.readonly()
        bf_rules = [r for r in config.ruleset if r.permission == "browser_fill"]
        assert len(bf_rules) == 1
        assert bf_rules[0].action == PermissionAction.DENY

    def test_readonly_denies_browser_upload(self) -> None:
        config = SecurityConfig.readonly()
        bu_rules = [r for r in config.ruleset if r.permission == "browser_upload"]
        assert len(bu_rules) == 1
        assert bu_rules[0].action == PermissionAction.DENY

    def test_readonly_denies_browser_download(self) -> None:
        config = SecurityConfig.readonly()
        bd_rules = [r for r in config.ruleset if r.permission == "browser_download"]
        assert len(bd_rules) == 1
        assert bd_rules[0].action == PermissionAction.DENY

    def test_readonly_asks_mcp_invoke(self) -> None:
        config = SecurityConfig.readonly()
        mcp_rules = [r for r in config.ruleset if r.permission == "mcp_invoke"]
        assert len(mcp_rules) == 1
        assert mcp_rules[0].action == PermissionAction.ASK

    def test_readonly_allows_delegate_agent(self) -> None:
        config = SecurityConfig.readonly()
        da_rules = [r for r in config.ruleset if r.permission == "delegate_agent"]
        assert len(da_rules) == 1
        assert da_rules[0].action == PermissionAction.ALLOW

    def test_readonly_with_allowed_roots(self) -> None:
        config = SecurityConfig.readonly(allowed_roots=("/home/user",))
        assert config.path_policy.allowed_roots == ("/home/user",)

    def test_readonly_with_workspace_label(self) -> None:
        config = SecurityConfig.readonly(workspace_label="Research")
        assert config.path_policy.workspace_label == "Research"

    def test_readonly_default_workspace_label_none(self) -> None:
        config = SecurityConfig.readonly()
        assert config.path_policy.workspace_label is None

    def test_readonly_capabilities_all(self) -> None:
        config = SecurityConfig.readonly()
        assert config.capabilities == frozenset({Capability("*", "*")})


class TestSecurityConfigWorkspace:
    """Tests for SecurityConfig.workspace() factory method."""

    def test_workspace_creates_config(self) -> None:
        config = SecurityConfig.workspace(allowed_roots=("/tmp",))
        assert isinstance(config, SecurityConfig)

    def test_workspace_yolo_disabled(self) -> None:
        config = SecurityConfig.workspace(allowed_roots=("/tmp",))
        assert config.yolo_mode_enabled is False

    def test_workspace_asks_shell_exec(self) -> None:
        config = SecurityConfig.workspace(allowed_roots=("/tmp",))
        shell_rules = [r for r in config.ruleset if r.permission == "shell_exec"]
        assert len(shell_rules) == 1
        assert shell_rules[0].action == PermissionAction.ASK

    def test_workspace_asks_code_interpreter(self) -> None:
        config = SecurityConfig.workspace(allowed_roots=("/tmp",))
        ci_rules = [r for r in config.ruleset if r.permission == "code_interpreter"]
        assert len(ci_rules) == 1
        assert ci_rules[0].action == PermissionAction.ASK

    def test_workspace_denies_browser_evaluate(self) -> None:
        config = SecurityConfig.workspace(allowed_roots=("/tmp",))
        be_rules = [r for r in config.ruleset if r.permission == "browser_evaluate"]
        assert len(be_rules) == 1
        assert be_rules[0].action == PermissionAction.DENY

    def test_workspace_asks_browser_upload(self) -> None:
        config = SecurityConfig.workspace(allowed_roots=("/tmp",))
        bu_rules = [r for r in config.ruleset if r.permission == "browser_upload"]
        assert len(bu_rules) == 1
        assert bu_rules[0].action == PermissionAction.ASK

    def test_workspace_asks_browser_download(self) -> None:
        config = SecurityConfig.workspace(allowed_roots=("/tmp",))
        bd_rules = [r for r in config.ruleset if r.permission == "browser_download"]
        assert len(bd_rules) == 1
        assert bd_rules[0].action == PermissionAction.ASK

    def test_workspace_asks_browser_fill(self) -> None:
        config = SecurityConfig.workspace(allowed_roots=("/tmp",))
        bf_rules = [r for r in config.ruleset if r.permission == "browser_fill"]
        assert len(bf_rules) == 1
        assert bf_rules[0].action == PermissionAction.ASK

    def test_workspace_asks_mcp_invoke(self) -> None:
        config = SecurityConfig.workspace(allowed_roots=("/tmp",))
        mcp_rules = [r for r in config.ruleset if r.permission == "mcp_invoke"]
        assert len(mcp_rules) == 1
        assert mcp_rules[0].action == PermissionAction.ASK

    def test_workspace_allows_delegate_agent(self) -> None:
        config = SecurityConfig.workspace(allowed_roots=("/tmp",))
        da_rules = [r for r in config.ruleset if r.permission == "delegate_agent"]
        assert len(da_rules) == 1
        assert da_rules[0].action == PermissionAction.ALLOW

    def test_workspace_with_shell_action_deny(self) -> None:
        config = SecurityConfig.workspace(allowed_roots=("/tmp",), shell_action=PermissionAction.DENY)
        shell_rules = [r for r in config.ruleset if r.permission == "shell_exec"]
        assert shell_rules[0].action == PermissionAction.DENY

    def test_workspace_with_workspace_label(self) -> None:
        config = SecurityConfig.workspace(allowed_roots=("/tmp",), workspace_label="My Workspace")
        assert config.path_policy.workspace_label == "My Workspace"

    def test_workspace_allowed_roots(self) -> None:
        config = SecurityConfig.workspace(allowed_roots=("/home/user/projects", "/tmp"))
        assert "/home/user/projects" in config.path_policy.allowed_roots
        assert "/tmp" in config.path_policy.allowed_roots


class TestSecurityConfigFullAccess:
    """Tests for SecurityConfig.full_access() factory method."""

    def test_full_access_creates_config(self) -> None:
        config = SecurityConfig.full_access()
        assert isinstance(config, SecurityConfig)

    def test_full_access_yolo_enabled(self) -> None:
        config = SecurityConfig.full_access()
        assert config.yolo_mode_enabled is True

    def test_full_access_allows_all(self) -> None:
        config = SecurityConfig.full_access()
        assert len(config.ruleset) == 1
        assert config.ruleset[0].permission == "*"
        assert config.ruleset[0].pattern == "*"
        assert config.ruleset[0].action == PermissionAction.ALLOW

    def test_full_access_capabilities_all(self) -> None:
        config = SecurityConfig.full_access()
        assert config.capabilities == frozenset({Capability("*", "*")})


class TestSecurityConfigRemoteExposed:
    """Tests for SecurityConfig.remote_exposed() factory method."""

    def test_remote_exposed_denies_shell_exec(self) -> None:
        config = SecurityConfig.remote_exposed()
        shell_rules = [r for r in config.ruleset if r.permission == "shell_exec"]
        assert len(shell_rules) == 1
        assert shell_rules[0].action == PermissionAction.DENY

    def test_remote_exposed_denies_desktop_control(self) -> None:
        config = SecurityConfig.remote_exposed()
        rules = [r for r in config.ruleset if r.permission == "desktop_control"]
        assert len(rules) == 1
        assert rules[0].action == PermissionAction.DENY

    def test_remote_exposed_yolo_disabled(self) -> None:
        config = SecurityConfig.remote_exposed()
        assert config.yolo_mode_enabled is False

    def test_remote_exposed_asks_mcp_invoke(self) -> None:
        config = SecurityConfig.remote_exposed()
        rules = [r for r in config.ruleset if r.permission == "mcp_invoke"]
        assert len(rules) == 1
        assert rules[0].action == PermissionAction.ASK

    def test_remote_exposed_denies_delegate_agent(self) -> None:
        config = SecurityConfig.remote_exposed()
        rules = [r for r in config.ruleset if r.permission == "delegate_agent"]
        assert len(rules) == 1
        assert rules[0].action == PermissionAction.DENY


class TestPathPolicyWorkspaceLabel:
    """Tests for PathPolicy.workspace_label field."""

    def test_default_workspace_label_none(self) -> None:
        pp = PathPolicy()
        assert pp.workspace_label is None

    def test_workspace_label_set(self) -> None:
        pp = PathPolicy(workspace_label="My Projects")
        assert pp.workspace_label == "My Projects"

    def test_workspace_label_with_allowed_roots(self) -> None:
        pp = PathPolicy(
            access_roots=access_roots_from_paths(("/home/user",)),
            workspace_label="Home",
        )
        assert pp.workspace_label == "Home"
        assert pp.allowed_roots == ("/home/user",)

    def test_workspace_label_frozen(self) -> None:
        pp = PathPolicy(workspace_label="Test")
        try:
            pp.workspace_label = "Changed"  # type: ignore[misc]
            assert False, "Should raise FrozenInstanceError"
        except AttributeError:
            pass


class TestSecurityConfigFrozen:
    """Tests for SecurityConfig frozen=True immutability."""

    def test_readonly_config_is_frozen(self) -> None:
        config = SecurityConfig.readonly()
        try:
            config.yolo_mode_enabled = True  # type: ignore[misc]
            assert False, "Should raise FrozenInstanceError"
        except AttributeError:
            pass

    def test_workspace_config_is_frozen(self) -> None:
        config = SecurityConfig.workspace(allowed_roots=("/tmp",))
        try:
            config.approval_timeout_seconds = 999  # type: ignore[misc]
            assert False, "Should raise FrozenInstanceError"
        except AttributeError:
            pass

    def test_full_access_config_is_frozen(self) -> None:
        config = SecurityConfig.full_access()
        try:
            config.yolo_mode_enabled = False  # type: ignore[misc]
            assert False, "Should raise FrozenInstanceError"
        except AttributeError:
            pass


class TestParseSecurityConfigAutoMode:
    """Tests for parse_security_config handling of auto_mode_enabled defaults."""

    def test_no_auto_mode_key_defaults_true(self) -> None:
        from myrm_agent_harness.agent.security.config import parse_security_config

        config = parse_security_config({"approvalTimeoutSeconds": 60})
        assert config is not None
        assert config.auto_mode_enabled is True

    def test_auto_mode_enabled_explicit_false(self) -> None:
        from myrm_agent_harness.agent.security.config import parse_security_config

        config = parse_security_config({"autoModeEnabled": False})
        assert config is not None
        assert config.auto_mode_enabled is False

    def test_auto_mode_enabled_explicit_true(self) -> None:
        from myrm_agent_harness.agent.security.config import parse_security_config

        config = parse_security_config({"autoModeEnabled": True})
        assert config is not None
        assert config.auto_mode_enabled is True


class TestMergeUserAndAgentPrivilegeCeiling:
    """Tests for _merge_user_and_agent anti-privilege-escalation guarantees."""

    def test_agent_cannot_escalate_deny_to_allow(self) -> None:
        from myrm_agent_harness.agent.security.channel_presets import _merge_user_and_agent
        from myrm_agent_harness.agent.security.engine import evaluate
        from myrm_agent_harness.agent.security.types import PermissionRule

        user = SecurityConfig.readonly()
        agent = SecurityConfig(
            ruleset=(PermissionRule("file_write", "*", PermissionAction.ALLOW),)
        )
        effective = _merge_user_and_agent(user, agent)
        assert effective is not None
        rule = evaluate("file_write", "/any/path.txt", effective.ruleset)
        assert rule.action == PermissionAction.DENY

    def test_agent_cannot_escalate_ask_to_allow(self) -> None:
        from myrm_agent_harness.agent.security.channel_presets import _merge_user_and_agent
        from myrm_agent_harness.agent.security.engine import evaluate
        from myrm_agent_harness.agent.security.types import PermissionRule

        user = SecurityConfig.workspace(allowed_roots=("/tmp",))
        agent = SecurityConfig(
            ruleset=(
                PermissionRule("mcp_invoke", "*", PermissionAction.ALLOW),
                PermissionRule("shell_exec", "*", PermissionAction.ALLOW),
            )
        )
        effective = _merge_user_and_agent(user, agent)
        assert effective is not None
        mcp_rule = evaluate("mcp_invoke", "server_tool", effective.ruleset)
        assert mcp_rule.action == PermissionAction.ASK
        shell_rule = evaluate("shell_exec", "rm -rf /", effective.ruleset)
        assert shell_rule.action == PermissionAction.ASK

    def test_agent_can_tighten_allow_to_deny_or_ask(self) -> None:
        from myrm_agent_harness.agent.security.channel_presets import _merge_user_and_agent
        from myrm_agent_harness.agent.security.engine import evaluate
        from myrm_agent_harness.agent.security.types import PermissionRule

        user = SecurityConfig.full_access()
        agent = SecurityConfig(
            ruleset=(
                PermissionRule("shell_exec", "*", PermissionAction.ASK),
                PermissionRule("file_write", "*.secret", PermissionAction.DENY),
            )
        )
        effective = _merge_user_and_agent(user, agent)
        assert effective is not None
        shell_rule = evaluate("shell_exec", "ls", effective.ruleset)
        assert shell_rule.action == PermissionAction.ASK
        file_rule = evaluate("file_write", "test.secret", effective.ruleset)
        assert file_rule.action == PermissionAction.DENY

    def test_agent_cannot_enable_yolo_without_user_global_yolo(self) -> None:
        from myrm_agent_harness.agent.security.channel_presets import _merge_user_and_agent

        user = SecurityConfig.workspace(allowed_roots=("/tmp",))
        assert user.yolo_mode_enabled is False
        agent = SecurityConfig(yolo_mode_enabled=True)
        effective = _merge_user_and_agent(user, agent)
        assert effective is not None
        assert effective.yolo_mode_enabled is False


    def test_auto_review_enabled_fallback_false(self) -> None:
        from myrm_agent_harness.agent.security.config import parse_security_config

        config = parse_security_config({"autoReviewEnabled": False})
        assert config is not None
        assert config.auto_mode_enabled is False

    def test_auto_mode_takes_priority_over_auto_review(self) -> None:
        from myrm_agent_harness.agent.security.config import parse_security_config

        config = parse_security_config({"autoModeEnabled": False, "autoReviewEnabled": True})
        assert config is not None
        assert config.auto_mode_enabled is False

    def test_empty_raw_returns_none(self) -> None:
        from myrm_agent_harness.agent.security.config import parse_security_config

        assert parse_security_config(None) is None
        assert parse_security_config({}) is None
