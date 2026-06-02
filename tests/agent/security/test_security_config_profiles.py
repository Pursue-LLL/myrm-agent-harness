"""Tests for SecurityConfig factory methods and PathPolicy.workspace_label."""

from __future__ import annotations

from myrm_agent_harness.agent.security.types import (
    Capability,
    PathPolicy,
    PermissionAction,
    SecurityConfig,
)


class TestSecurityConfigReadonly:
    """Tests for SecurityConfig.readonly() factory method."""

    def test_readonly_creates_config(self) -> None:
        config = SecurityConfig.readonly()
        assert isinstance(config, SecurityConfig)

    def test_readonly_yolo_disabled(self) -> None:
        config = SecurityConfig.readonly()
        assert config.yolo_mode_enabled is False

    def test_readonly_auto_mode_disabled(self) -> None:
        config = SecurityConfig.readonly()
        assert config.auto_mode_enabled is False

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
        config = SecurityConfig.workspace(
            allowed_roots=("/tmp",), shell_action=PermissionAction.DENY
        )
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


class TestPathPolicyWorkspaceLabel:
    """Tests for PathPolicy.workspace_label field."""

    def test_default_workspace_label_none(self) -> None:
        pp = PathPolicy()
        assert pp.workspace_label is None

    def test_workspace_label_set(self) -> None:
        pp = PathPolicy(workspace_label="My Projects")
        assert pp.workspace_label == "My Projects"

    def test_workspace_label_with_allowed_roots(self) -> None:
        pp = PathPolicy(allowed_roots=("/home/user",), workspace_label="Home")
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
