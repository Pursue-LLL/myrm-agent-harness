"""Environment example file generator for skills with credential requirements.

Generates `.env.example` files documenting required credential paths,
improving developer onboarding experience.

[INPUT]
- types::SkillMetadata (POS: skill metadata with credential requirements)
- pathlib::Path (stdlib: file operations)

[OUTPUT]
- EnvExampleGenerator: generates .env.example files
- generate_env_example_content(): content generator function

[POS]
Developer experience enhancement. Provides clear documentation of required
credential files and their expected locations.
"""

from __future__ import annotations

import logging
from pathlib import Path

from myrm_agent_harness.backends.skills.types import SkillMetadata

logger = logging.getLogger(__name__)


class EnvExampleGenerator:
    """Generates .env.example files for skills with credential requirements."""

    def __init__(self, workspace_root: Path) -> None:
        """Initialize generator.

        Args:
            workspace_root: Absolute path to workspace root
        """
        self._workspace_root = workspace_root.resolve()

    def generate_for_skill(self, skill: SkillMetadata) -> str | None:
        """Generate .env.example content for a single skill.

        Args:
            skill: Skill metadata

        Returns:
            .env.example content string, or None if skill has no credential requirements
        """
        if not skill.required_credential_files and not skill.credential_env_mapping:
            return None

        lines: list[str] = []

        # Header
        lines.append(f"# Environment configuration for {skill.name}")
        lines.append(f"# Generated from skill: {skill.storage_path}")
        lines.append("#")

        # Required credential files
        if skill.required_credential_files:
            lines.append("# Required credential files (relative to workspace root):")
            for file_path in skill.required_credential_files:
                lines.append(f"#   - {file_path}")
            lines.append("#")

        # Environment variable mappings
        if skill.credential_env_mapping:
            lines.append("# Environment variables for credential files:")
            for env_name, file_path in skill.credential_env_mapping.items():
                # Show example absolute path (workspace_root + file_path)
                example_path = self._workspace_root / file_path
                lines.append(f"{env_name}={example_path}")

        lines.append("")  # Trailing newline
        return "\n".join(lines)

    def generate_for_skills(self, skills: list[SkillMetadata]) -> str:
        """Generate combined .env.example for multiple skills.

        Args:
            skills: List of skill metadata

        Returns:
            Combined .env.example content string
        """
        lines: list[str] = []

        # Header
        lines.append("# Combined environment configuration")
        lines.append("# Generated from active skills with credential requirements")
        lines.append("#")
        lines.append("# Copy this file to .env and fill in actual credential paths")
        lines.append("")

        # Group by skill
        for skill in skills:
            skill_content = self.generate_for_skill(skill)
            if skill_content:
                lines.append(skill_content)
                lines.append("")  # Empty line between skills

        return "\n".join(lines)

    def write_env_example(
        self,
        skills: list[SkillMetadata],
        output_path: Path | None = None,
    ) -> Path:
        """Generate and write .env.example file.

        Args:
            skills: List of skill metadata
            output_path: Optional output file path (defaults to workspace_root/.env.example)

        Returns:
            Path to written .env.example file
        """
        if output_path is None:
            output_path = self._workspace_root / ".env.example"

        content = self.generate_for_skills(skills)

        output_path.write_text(content, encoding="utf-8")
        logger.info("Generated .env.example at %s", output_path)

        return output_path


def generate_env_example_content(
    skill: SkillMetadata,
    workspace_root: Path,
) -> str | None:
    """Standalone function to generate .env.example content for a skill.

    Args:
        skill: Skill metadata
        workspace_root: Workspace root directory

    Returns:
        .env.example content string, or None if skill has no credential requirements
    """
    generator = EnvExampleGenerator(workspace_root)
    return generator.generate_for_skill(skill)
