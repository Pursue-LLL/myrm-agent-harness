"""Unit tests for core.security.types — security type definitions and profiles.

Covers default value factories, pre-built SecurityConfig profiles
(readonly / workspace / full_access / remote_exposed), access-root
helpers, and user-credential context propagation.
"""

from __future__ import annotations

import asyncio

import pytest

from myrm_agent_harness.core.security.types import (
    AccessRoot,
    Capability,
    EphemeralUserCredential,
    PathPolicy,
    PermissionAction,
    PermissionRule,
    PIIAction,
    PrivacyPolicy,
    PrivacyRoutingConfig,
    ReviewDecision,
    SecurityConfig,
    SensitivityLevel,
    access_roots_from_paths,
    propagate_user_credentials,
    user_credentials_ctx,
    with_user_credentials,
)


class TestProfileFactories:
    """SecurityConfig factory methods produce the expected postures."""

    def test_readonly_profile_denies_writes_and_shell(self) -> None:
        cfg = SecurityConfig.readonly(allowed_roots=("/data",), workspace_label="analysis")

        actions = {r.permission: r.action for r in cfg.ruleset}
        assert actions["shell_exec"] is PermissionAction.DENY
        assert actions["file_write"] is PermissionAction.DENY
        assert actions["mcp_invoke"] is PermissionAction.ASK
        assert cfg.path_policy.allowed_roots == ("/data",)
        assert cfg.path_policy.workspace_label == "analysis"

    def test_workspace_profile_scopes_roots_and_shell(self) -> None:
        cfg = SecurityConfig.workspace(
            allowed_roots=("/workspace",),
            shell_action=PermissionAction.DENY,
            workspace_label="ws",
        )

        actions = {r.permission: r.action for r in cfg.ruleset}
        assert actions["shell_exec"] is PermissionAction.DENY
        assert actions["code_interpreter"] is PermissionAction.ASK
        assert cfg.path_policy.allowed_roots == ("/workspace",)
        assert cfg.path_policy.workspace_label == "ws"

    def test_full_access_profile_enables_yolo(self) -> None:
        cfg = SecurityConfig.full_access()

        assert cfg.yolo_mode_enabled is True
        assert cfg.ruleset == (PermissionRule("*", "*", PermissionAction.ALLOW),)

    def test_remote_exposed_profile_denies_destructive_tools(self) -> None:
        cfg = SecurityConfig.remote_exposed()

        assert cfg.yolo_mode_enabled is False
        actions = {r.permission: r.action for r in cfg.ruleset}
        assert actions["shell_exec"] is PermissionAction.DENY
        assert actions["desktop_control"] is PermissionAction.DENY
        assert actions["delegate_agent"] is PermissionAction.DENY
        assert cfg.capabilities == frozenset({Capability("*", "*")})

    def test_default_config_uses_dangerous_paths_factory(self) -> None:
        cfg = SecurityConfig()

        assert "/dev" in cfg.path_policy.forbidden_paths
        assert "/proc" in cfg.path_policy.forbidden_paths
        assert cfg.privacy_policy.enabled is False


class TestAccessRootHelpers:
    """access_roots_from_paths and PathPolicy.allowed_roots."""

    def test_access_roots_from_paths_builds_roots(self) -> None:
        roots = access_roots_from_paths(("/a", "/b"), writable=False, source="test")

        assert roots == (
            AccessRoot(path="/a", writable=False, source="test"),
            AccessRoot(path="/b", writable=False, source="test"),
        )

    def test_path_policy_allowed_roots_property(self) -> None:
        policy = PathPolicy(access_roots=access_roots_from_paths(("/a",)))

        assert policy.allowed_roots == ("/a",)


class TestEnumsAndValues:
    """Enum and dataclass value semantics."""

    def test_permission_action_values(self) -> None:
        assert PermissionAction.ALLOW.value == "allow"
        assert PermissionAction.ASK.value == "ask"
        assert PermissionAction.DENY.value == "deny"

    def test_sensitivity_level_values(self) -> None:
        assert SensitivityLevel.S1.value == "s1"
        assert SensitivityLevel.S2.value == "s2"
        assert SensitivityLevel.S3.value == "s3"

    def test_pii_action_values(self) -> None:
        assert PIIAction.WARN.value == "warn"
        assert PIIAction.REDACT.value == "redact"
        assert PIIAction.PSEUDONYMIZE.value == "pseudonymize"
        assert PIIAction.BLOCK.value == "block"

    def test_review_decision_values(self) -> None:
        assert ReviewDecision.ALLOW.value == "allow"
        assert ReviewDecision.DENY.value == "deny"
        assert ReviewDecision.UNCERTAIN.value == "uncertain"

    def test_privacy_policy_defaults(self) -> None:
        policy = PrivacyPolicy()

        assert policy.enabled is False
        assert policy.s2_action is PIIAction.WARN
        assert policy.s3_action is PIIAction.REDACT

    def test_privacy_policy_needs_pseudonym_store(self) -> None:
        """needs_pseudonym_store is the single source of truth for store init."""
        assert PrivacyPolicy().needs_pseudonym_store is False

        pseudonymize = PrivacyPolicy(
            enabled=True,
            s2_action=PIIAction.PSEUDONYMIZE,
            s3_action=PIIAction.REDACT,
        )
        assert pseudonymize.needs_pseudonym_store is True

        deep_scan_only = PrivacyPolicy(
            enabled=True,
            s2_action=PIIAction.REDACT,
            s3_action=PIIAction.REDACT,
            deep_scan=True,
        )
        assert deep_scan_only.needs_pseudonym_store is True

        no_store_needed = PrivacyPolicy(
            enabled=True,
            s2_action=PIIAction.WARN,
            s3_action=PIIAction.REDACT,
            deep_scan=False,
        )
        assert no_store_needed.needs_pseudonym_store is False

    def test_privacy_routing_config_constructible(self) -> None:
        cfg = PrivacyRoutingConfig()

        assert cfg.s2_strategy in {"cloud_after_redact", "local"}


class TestUserCredentials:
    """with_user_credentials and propagate_user_credentials context capture."""

    CRED = EphemeralUserCredential(issuer="github", token="ghu_test_token")

    @pytest.mark.asyncio
    async def test_with_user_credentials_binds_and_cleans_up(self) -> None:
        assert user_credentials_ctx.get() == ()

        async with with_user_credentials((self.CRED,)):
            assert user_credentials_ctx.get() == (self.CRED,)

        assert user_credentials_ctx.get() == ()

    def test_propagate_user_credentials_sync(self) -> None:
        seen: list[tuple[EphemeralUserCredential, ...]] = []

        @propagate_user_credentials
        def read_ctx() -> None:
            seen.append(user_credentials_ctx.get())

        read_ctx()
        assert seen == [()]

    @pytest.mark.asyncio
    async def test_propagate_user_credentials_async_keeps_credentials(self) -> None:
        captured: list[tuple[EphemeralUserCredential, ...]] = []

        async def read_ctx() -> None:
            await asyncio.sleep(0)
            captured.append(user_credentials_ctx.get())

        # 装饰器在 with 块内执行时捕获当前 ctx 的 credentials。
        async with with_user_credentials((self.CRED,)):
            decorated = propagate_user_credentials(read_ctx)

        # 离开 with 块后调用，wrapper 内部仍是捕获时的 credentials。
        await decorated()

        assert captured == [(self.CRED,)]

    @pytest.mark.asyncio
    async def test_propagate_user_credentials_async_without_context(self) -> None:
        captured: list[tuple[EphemeralUserCredential, ...]] = []

        @propagate_user_credentials
        async def read_ctx() -> None:
            captured.append(user_credentials_ctx.get())

        await read_ctx()
        assert captured == [()]
