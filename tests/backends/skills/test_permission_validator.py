"""Tests for the skill permission validator mapping and runtime checks.

Guards the permission-type-to-enum mapping against drift: every permission
type emitted by the guardrail boundary (resolved via the tool registry SSOT,
plus direct permission names) must resolve to a SkillPermission, otherwise the
runtime check silently allows the call.
"""

from __future__ import annotations

from myrm_agent_harness.backends.skills.permission_validator import (
    _PERMISSION_TYPE_TO_SKILL_PERMISSION,
    check_permission_for_tool_call,
    log_permission_usage,
    map_permission_to_skill_permission,
    set_permission_usage_callback,
    validate_skill_permissions,
)
from myrm_agent_harness.backends.skills.types_enums import SkillPermission


def test_standard_permission_types_resolve_to_enum() -> None:
    """Every direct permission name must map to a SkillPermission."""
    assert map_permission_to_skill_permission("file_read") == SkillPermission.FILE_READ
    assert map_permission_to_skill_permission("file_write") == SkillPermission.FILE_WRITE
    assert map_permission_to_skill_permission("file_delete") == SkillPermission.FILE_DELETE
    assert map_permission_to_skill_permission("shell_exec") == SkillPermission.SHELL_EXEC
    assert map_permission_to_skill_permission("code_interpreter") == SkillPermission.CODE_INTERPRETER
    assert map_permission_to_skill_permission("network_access") == SkillPermission.NETWORK_ACCESS
    assert map_permission_to_skill_permission("web_fetch") == SkillPermission.NETWORK_ACCESS
    assert map_permission_to_skill_permission("env_var_access") == SkillPermission.ENV_VAR_ACCESS


def test_tool_registry_ssot_types_resolve_to_enum() -> None:
    """Abstract permission types emitted by tool_registry must map to enums.

    Guards the guardrail boundary (which resolves via the tool registry SSOT)
    against mapping drift: browser/web/search types must land on NETWORK_ACCESS,
    otherwise a loaded skill could silently bypass network gating.
    """
    assert map_permission_to_skill_permission("net_fetch") == SkillPermission.NETWORK_ACCESS
    assert map_permission_to_skill_permission("web_search_tool") == SkillPermission.NETWORK_ACCESS
    for browser_type in (
        "browser_navigate",
        "browser_read",
        "browser_click",
        "browser_fill",
        "browser_scroll",
        "browser_upload",
        "browser_download",
        "browser_evaluate",
        "browser_session",
        "browser_manage",
        "browser_execute_script_tool",
    ):
        assert map_permission_to_skill_permission(browser_type) == SkillPermission.NETWORK_ACCESS


def test_every_skill_permission_has_a_mapping_key() -> None:
    """No SkillPermission value may be unreachable from the mapping table."""
    mapped = set(_PERMISSION_TYPE_TO_SKILL_PERMISSION.values())
    assert mapped == set(SkillPermission)


def test_every_ssot_skill_domain_type_is_mapped() -> None:
    """All tool_registry permission types in the skill domain must be mapped.

    Unmapped types silently allow the tool call in the runtime check, so this
    assertion fails loudly whenever the SSOT grows a new skill-domain type.
    """
    from myrm_agent_harness.core.security.tool_registry.registry import (
        BUILTIN_TOOL_NAMES,
        TOOL_PERMISSION_MAP,
    )

    ssot_types = set(TOOL_PERMISSION_MAP.values()) | set(BUILTIN_TOOL_NAMES)
    skill_domain = ssot_types & {
        "file_read",
        "file_write",
        "file_delete",
        "shell_exec",
        "code_interpreter",
        "net_fetch",
        "web_search_tool",
        "browser_navigate",
        "browser_read",
        "browser_click",
        "browser_fill",
        "browser_scroll",
        "browser_upload",
        "browser_download",
        "browser_evaluate",
        "browser_session",
        "browser_manage",
        "browser_execute_script_tool",
    }
    assert skill_domain <= set(_PERMISSION_TYPE_TO_SKILL_PERMISSION)


def test_check_allows_granted_permission() -> None:
    assert check_permission_for_tool_call(
        "network_access", {SkillPermission.NETWORK_ACCESS}
    ) == (True, "")
    assert check_permission_for_tool_call(
        "env_var_access", {SkillPermission.ENV_VAR_ACCESS}
    ) == (True, "")


def test_check_denies_ungranted_permission() -> None:
    allowed, reason = check_permission_for_tool_call("network_access", set())
    assert allowed is False
    assert "network_access" in reason

    allowed, reason = check_permission_for_tool_call("env_var_access", set())
    assert allowed is False
    assert "env_var_access" in reason


def test_check_denies_partial_grants() -> None:
    """A file-only grant must not cover network access."""
    allowed, _ = check_permission_for_tool_call(
        "network_access", {SkillPermission.FILE_READ, SkillPermission.FILE_WRITE}
    )
    assert allowed is False


def test_unknown_permission_type_allows() -> None:
    """Unmapped types remain non-applicable and must not raise."""
    assert check_permission_for_tool_call("unknown_permission", set()) == (True, "")


def test_map_unknown_returns_none() -> None:
    assert map_permission_to_skill_permission("unknown") is None


def test_validate_skill_permissions_accepts_full_grants() -> None:
    required = [SkillPermission.FILE_WRITE, SkillPermission.SHELL_EXEC]
    granted = {
        SkillPermission.FILE_WRITE,
        SkillPermission.SHELL_EXEC,
        SkillPermission.NETWORK_ACCESS,
    }
    assert validate_skill_permissions(required, granted) == (True, [])


def test_validate_skill_permissions_reports_missing() -> None:
    required = [SkillPermission.FILE_WRITE, SkillPermission.SHELL_EXEC]
    granted = {SkillPermission.FILE_WRITE}
    valid, missing = validate_skill_permissions(required, granted)
    assert valid is False
    assert missing == [SkillPermission.SHELL_EXEC]


def test_set_and_clear_permission_usage_callback() -> None:
    received: list[tuple[str, str, str, str, bool, str]] = []

    def _callback(
        user_id: str,
        skill_id: str,
        permission: str,
        operation: str,
        allowed: bool,
        deny_reason: str,
    ) -> None:
        received.append((user_id, skill_id, permission, operation, allowed, deny_reason))

    set_permission_usage_callback(_callback)
    try:
        log_permission_usage(
            "u1", "s1", "file_write", "/tmp/a.txt", True, ""
        )
        assert received == [("u1", "s1", "file_write", "/tmp/a.txt", True, "")]
    finally:
        set_permission_usage_callback(None)


def test_permission_usage_callback_exception_is_swallowed() -> None:
    def _broken(
        user_id: str,
        skill_id: str,
        permission: str,
        operation: str,
        allowed: bool,
        deny_reason: str,
    ) -> None:
        raise RuntimeError("boom")

    set_permission_usage_callback(_broken)
    try:
        # Must not raise; failure is logged by the framework.
        log_permission_usage("u1", "s1", "file_write", "/tmp/a.txt", True)
    finally:
        set_permission_usage_callback(None)


def test_permission_usage_logs_locally_without_callback() -> None:
    # No callback registered (module default) → falls back to local INFO log.
    log_permission_usage("u1", "s1", "shell_exec", "ls", False, "denied")
