"""Skill Permission Validator

Validates that skills have the required permissions to perform operations.

[INPUT]

[OUTPUT]
- map_permission_to_skill_permission(): Map permission types to SkillPermission
- validate_skill_permissions(): Check if granted permissions cover required permissions
- check_permission_for_tool_call(): Runtime permission check
- log_permission_usage(): Log permission usage for audit and analytics

[POS]
Framework-layer permission mapping for skills. Does NOT depend on user identity
or business logic. Business layer must query granted permissions from database
and pass them here for validation.

Usage logging is framework-layer (pure data collection) while storage is
business-layer responsibility (database write).
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from myrm_agent_harness.backends.skills.types import SkillPermission

logger = logging.getLogger(__name__)

# Global permission usage logger (set by business layer)
_permission_usage_callback: Callable[[str, str, str, str, bool, str], None] | None = None


# Mapping from security permission types to SkillPermission
_PERMISSION_TYPE_TO_SKILL_PERMISSION: dict[str, SkillPermission] = {
    # File operations
    "file_read": SkillPermission.FILE_READ,
    "file_write": SkillPermission.FILE_WRITE,
    "file_delete": SkillPermission.FILE_DELETE,
    # Code execution
    "shell_exec": SkillPermission.SHELL_EXEC,
    "code_interpreter": SkillPermission.CODE_INTERPRETER,
    # Network
    "browser_navigate": SkillPermission.NETWORK_ACCESS,
    "web_fetch": SkillPermission.NETWORK_ACCESS,
    # Environment
    "env_read": SkillPermission.ENV_VAR_ACCESS,
    "env_write": SkillPermission.ENV_VAR_ACCESS,
}


def map_permission_to_skill_permission(permission_type: str) -> SkillPermission | None:
    """Map a security permission type to a SkillPermission.

    Args:
        permission_type: Permission type string (e.g., "shell_exec", "file_write")

    Returns:
        Corresponding SkillPermission, or None if no mapping exists

    Examples:
        >>> map_permission_to_skill_permission("shell_exec")
        SkillPermission.SHELL_EXEC

        >>> map_permission_to_skill_permission("file_write")
        SkillPermission.FILE_WRITE

        >>> map_permission_to_skill_permission("unknown")
        None
    """
    return _PERMISSION_TYPE_TO_SKILL_PERMISSION.get(permission_type)


def validate_skill_permissions(
    required_permissions: list[SkillPermission],
    granted_permissions: set[SkillPermission],
) -> tuple[bool, list[SkillPermission]]:
    """Validate that granted permissions cover all required permissions.

    Args:
        required_permissions: Permissions required by the skill
        granted_permissions: Permissions granted to the skill by the user

    Returns:
        Tuple of (is_valid, missing_permissions)
        - is_valid: True if all required permissions are granted
        - missing_permissions: List of permissions that are required but not granted

    Examples:
        >>> required = [SkillPermission.FILE_WRITE, SkillPermission.SHELL_EXEC]
        >>> granted = {SkillPermission.FILE_WRITE, SkillPermission.SHELL_EXEC, SkillPermission.NETWORK_ACCESS}
        >>> validate_skill_permissions(required, granted)
        (True, [])

        >>> granted = {SkillPermission.FILE_WRITE}
        >>> validate_skill_permissions(required, granted)
        (False, [SkillPermission.SHELL_EXEC])
    """
    missing = [perm for perm in required_permissions if perm not in granted_permissions]
    return (len(missing) == 0, missing)


def check_permission_for_tool_call(
    permission_type: str,
    granted_permissions: set[SkillPermission],
) -> tuple[bool, str]:
    """Check if a tool call is allowed given the granted permissions.

    This is the main entry point for runtime permission checks.

    Args:
        permission_type: Permission type of the tool call (e.g., "shell_exec")
        granted_permissions: Set of permissions granted to the skill

    Returns:
        Tuple of (is_allowed, reason)
        - is_allowed: True if the tool call is permitted
        - reason: Empty if allowed, error message if denied

    Examples:
        >>> granted = {SkillPermission.FILE_WRITE}
        >>> check_permission_for_tool_call("file_write", granted)
        (True, "")

        >>> check_permission_for_tool_call("shell_exec", granted)
        (False, "Permission denied: shell_exec requires SkillPermission.SHELL_EXEC")
    """
    required_permission = map_permission_to_skill_permission(permission_type)

    # If no mapping exists, permission check is not applicable for skills
    if required_permission is None:
        return (True, "")

    if required_permission in granted_permissions:
        return (True, "")

    return (
        False,
        f"Permission denied: {permission_type} requires {required_permission.value}",
    )


def set_permission_usage_callback(
    callback: Callable[[str, str, str, str, bool, str], None] | None,
) -> None:
    """Set the callback for logging permission usage.

    Business layer should call this during initialization to register
    its logging function. The callback receives:
    - user_id: User identifier (from Agent context)
    - skill_id: Skill identifier
    - permission: Permission type (e.g., "file_write")
    - operation: Operation details (e.g., file path, command)
    - allowed: Whether the operation was allowed
    - deny_reason: Reason if denied (empty if allowed)

    Args:
        callback: Logging function or None to disable
    """
    global _permission_usage_callback
    _permission_usage_callback = callback


def log_permission_usage(
    user_id: str,
    skill_id: str,
    permission: str,
    operation: str,
    allowed: bool,
    deny_reason: str = "",
) -> None:
    """Log a permission usage event.

    Framework-layer logging entry point. Delegates to business layer callback
    if registered (for database persistence), otherwise logs locally.

    Args:
        user_id: User identifier (from Agent context)
        skill_id: Skill identifier
        permission: Permission type (e.g., "file_write", "shell_exec")
        operation: Operation details (file path, command, URL, etc.)
        allowed: Whether the operation was allowed
        deny_reason: Reason if denied (empty if allowed)

    Examples:
        >>> log_permission_usage("user123", "my-skill", "file_write", "/workspace/data.txt", True)
        >>> log_permission_usage("user123", "my-skill", "shell_exec", "rm -rf /", False, "Permission denied")
    """
    if _permission_usage_callback:
        try:
            _permission_usage_callback(user_id, skill_id, permission, operation, allowed, deny_reason)
        except Exception as e:
            logger.error(f"Permission usage callback failed: {e}", exc_info=True)
    else:
        logger.info(
            f"SKILL_PERMISSION_USAGE user={user_id} skill={skill_id} permission={permission} "
            f"operation={operation!r} allowed={allowed} reason={deny_reason!r}"
        )
