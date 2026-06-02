"""Skill instance templates for quick setup.

Framework layer provides the InstanceTemplate mechanism (data type).
Business layer defines specific templates (e.g., github-personal, mysql-prod).

Design principle: Framework provides reusable mechanisms, not business-specific data.

[INPUT]
- (none)

[OUTPUT]
- InstanceTemplate: Template for creating skill instances.

[POS]
Skill instance templates for quick setup.
"""

from dataclasses import dataclass


@dataclass
class InstanceTemplate:
    """Template for creating skill instances.

    Framework-provided data type for instance templates.
    Business layer uses this to define concrete templates.

    Example (business layer):
        github_personal = InstanceTemplate(
            template_id="github-personal",
            name="Personal Account",
            description="GitHub personal account with PAT token",
            env_overrides={"GITHUB_TOKEN": "<your_token>"},
            config_overrides={},
        )
    """

    template_id: str
    """Unique template identifier (e.g., 'github-personal', 'mysql-prod')"""

    name: str
    """Human-readable template name"""

    description: str
    """Template description for UI display"""

    env_overrides: dict[str, str]
    """Default environment variable overrides"""

    config_overrides: dict[str, object]
    """Default configuration overrides"""
