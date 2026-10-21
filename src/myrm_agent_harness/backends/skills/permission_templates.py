"""Skill Permission Templates

Predefined permission sets for common Skill categories.

[INPUT]

[OUTPUT]
- PermissionTemplate: Enum of standard templates
- TEMPLATE_PERMISSIONS: Mapping from template to permission set
- get_template_permissions(): Helper to get permissions for a template

[POS]
Framework-layer permission templates that provide out-of-the-box permission
sets for common Skill categories. Business layer can use these templates or
define custom ones.

Design rationale:
- DEVELOPER_TOOLS: For development/debugging tools (code formatters, linters)
- DATA_ANALYSIS: For data science/analytics tools (pandas, numpy)
- WEB_AUTOMATION: For web scraping/automation tools (playwright, selenium)
- SYSTEM_ADMIN: For system administration tools (WARNING: dangerous!)
- READONLY: For read-only tools (documentation viewers, code search)
"""

from __future__ import annotations

from enum import StrEnum

from myrm_agent_harness.backends.skills.types import SkillPermission

__all__ = ["TEMPLATE_PERMISSIONS", "PermissionTemplate", "get_template_permissions"]


class PermissionTemplate(StrEnum):
    """Standard permission templates for common Skill categories."""

    DEVELOPER_TOOLS = "developer_tools"
    """Development tools (code formatters, linters, git helpers)

    Permissions: file_read, file_write, shell_exec
    """

    DATA_ANALYSIS = "data_analysis"
    """Data science and analytics tools (pandas, numpy, matplotlib)

    Permissions: file_read, code_interpreter
    """

    WEB_AUTOMATION = "web_automation"
    """Web scraping and automation tools (playwright, selenium, requests)

    Permissions: network_access, file_write
    """

    SYSTEM_ADMIN = "system_admin"
    """System administration tools (WARNING: grants ALL permissions!)

    Permissions: ALL (file_read, file_write, file_delete, shell_exec,
                      code_interpreter, network_access, env_var_access)

    DANGER: Only grant this template if you fully trust the Skill author.
    """

    READONLY = "readonly"
    """Read-only tools (documentation viewers, code search, file browsers)

    Permissions: file_read only
    """


# Standard template permissions mapping
TEMPLATE_PERMISSIONS: dict[PermissionTemplate, set[SkillPermission]] = {
    PermissionTemplate.DEVELOPER_TOOLS: {
        SkillPermission.FILE_READ,
        SkillPermission.FILE_WRITE,
        SkillPermission.SHELL_EXEC,
    },
    PermissionTemplate.DATA_ANALYSIS: {
        SkillPermission.FILE_READ,
        SkillPermission.CODE_INTERPRETER,
    },
    PermissionTemplate.WEB_AUTOMATION: {
        SkillPermission.NETWORK_ACCESS,
        SkillPermission.FILE_WRITE,
    },
    PermissionTemplate.SYSTEM_ADMIN: {
        SkillPermission.FILE_READ,
        SkillPermission.FILE_WRITE,
        SkillPermission.FILE_DELETE,
        SkillPermission.SHELL_EXEC,
        SkillPermission.CODE_INTERPRETER,
        SkillPermission.NETWORK_ACCESS,
        SkillPermission.ENV_VAR_ACCESS,
    },
    PermissionTemplate.READONLY: {
        SkillPermission.FILE_READ,
    },
}


def get_template_permissions(template: PermissionTemplate) -> set[SkillPermission]:
    """Get permissions for a given template.

    Args:
        template: The permission template

    Returns:
        Set of SkillPermissions for this template

    Raises:
        KeyError: If template not found in TEMPLATE_PERMISSIONS

    Example:
        >>> perms = get_template_permissions(PermissionTemplate.DEVELOPER_TOOLS)
        >>> SkillPermission.FILE_WRITE in perms
        True
    """
    return TEMPLATE_PERMISSIONS[template]
