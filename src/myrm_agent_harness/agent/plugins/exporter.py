"""Single-skill convenience packer on top of the plugin bundle writer.

Builds a spec-1.0.0 plugin that carries exactly one skill. The skill keeps its
real directory name (so the import side reproduces the same skill name), while
the package identity is derived losslessly from the display name.

[INPUT]
-- .writer::PluginBundleSpec / build_plugin_bundle (POS: unified bundle writer)
-- .rules::plugin_identity / is_excluded_path (POS: naming and path-exclusion rules)

[OUTPUT]
-- AgentPluginPacker.package_skill_as_plugin: skill files → plugin ZIP result.

[POS]
Thin wrapper; all ZIP assembly lives in writer.py (no duplicate packaging logic).
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from myrm_agent_harness.agent.skills.market.sanitizer import SKILL_MD_FILE

from .rules import is_excluded_path, plugin_identity
from .writer import PluginBundleSpec, PluginPackageResult, build_plugin_bundle

logger = logging.getLogger(__name__)


def canonical_plugin_name(raw_name: str) -> str:
    """Sanitize a skill name into a valid Agent Plugins 1.0.0 plugin name (spec §5.5)."""
    return plugin_identity(raw_name)


__all__ = ["AgentPluginPacker", "PluginPackageResult", "canonical_plugin_name"]


class AgentPluginPacker:
    """Agent Plugins 1.0.0 single-skill packer."""

    def package_skill_as_plugin(
        self,
        skill_name: str,
        file_contents: Mapping[str, bytes | str],
        *,
        version: str = "1.0.0",
        description: str | None = None,
        author_name: str = "Myrm User",
        keywords: list[str] | None = None,
        extra_extensions: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> PluginPackageResult:
        """Package one skill file set as a standard plugin.

        Layout: ``plugin.json`` + ``skills/<skill name>/SKILL.md`` and its resources.
        Forbidden and hidden files are dropped; everything else ships verbatim.
        """
        from myrm_agent_harness.agent.skills.packaging.validator import is_forbidden_file, parse_skill_md

        skill_md = file_contents.get(SKILL_MD_FILE)
        if skill_md is None:
            return PluginPackageResult(False, None, None, f"Missing required {SKILL_MD_FILE}")

        skill_info = parse_skill_md(skill_md.decode("utf-8") if isinstance(skill_md, bytes) else skill_md)
        actual_name = skill_info.name or skill_name
        files = {
            path: content.encode("utf-8") if isinstance(content, str) else content
            for path, content in file_contents.items()
            if not is_forbidden_file(path) and not is_excluded_path(path)
        }
        extensions: dict[str, Mapping[str, Any]] = {
            "ai.myrm.skill": {"originalName": actual_name, "exportedBy": "Myrm Agent Platform"},
            **(extra_extensions or {}),
        }
        spec = PluginBundleSpec(
            name=plugin_identity(actual_name),
            version=skill_info.version or version,
            description=description or skill_info.description or f"Skill plugin {actual_name}",
            author_name=author_name,
            keywords=tuple(keywords or ()),
            skills={actual_name: files},
            extensions=extensions,
        )
        return build_plugin_bundle(spec)
