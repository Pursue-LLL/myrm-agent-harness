"""Tests for the skill permission validator mapping and runtime checks.

Guards the permission-type-to-enum mapping against drift: every value emitted
by the guardrail boundary inference (file/shell/code/network/env) must resolve
to a SkillPermission, otherwise the runtime check silently allows the call.
"""

from __future__ import annotations

from myrm_agent_harness.backends.skills.permission_validator import (
    _PERMISSION_TYPE_TO_SKILL_PERMISSION,
    check_permission_for_tool_call,
    map_permission_to_skill_permission,
)
from myrm_agent_harness.backends.skills.types_enums import SkillPermission


def test_standard_permission_types_resolve_to_enum() -> None:
    """Every boundary-inferred permission type must map to a SkillPermission."""
    assert map_permission_to_skill_permission("file_read") == SkillPermission.FILE_READ
    assert map_permission_to_skill_permission("file_write") == SkillPermission.FILE_WRITE
    assert map_permission_to_skill_permission("file_delete") == SkillPermission.FILE_DELETE
    assert map_permission_to_skill_permission("shell_exec") == SkillPermission.SHELL_EXEC
    assert map_permission_to_skill_permission("code_interpreter") == SkillPermission.CODE_INTERPRETER
    assert map_permission_to_skill_permission("network_access") == SkillPermission.NETWORK_ACCESS
    assert map_permission_to_skill_permission("env_var_access") == SkillPermission.ENV_VAR_ACCESS


def test_every_skill_permission_has_a_mapping_key() -> None:
    """No SkillPermission value may be unreachable from the mapping table."""
    mapped = set(_PERMISSION_TYPE_TO_SKILL_PERMISSION.values())
    assert mapped == set(SkillPermission)


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
