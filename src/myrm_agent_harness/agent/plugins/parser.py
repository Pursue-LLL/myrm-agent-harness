"""Agent Plugins 1.0.0 package parser.

Orchestrates secure extraction and discovery with per-component failure isolation
(spec §6, §7, §11.3):
  - A fatal ``plugin.json`` violation rejects the whole plugin.
  - A bad skill is skipped; other skills and components still load.
  - A top-level ``mcp.json`` failure disables MCP; an invalid server variant is
    skipped; neither ever affects skills.

[INPUT]
-- .agents::discover_agents / discover_workspace_files (POS: client-specific component discovery)
-- .manifest::parse_manifest (POS: closed-schema plugin.json manifest validation)
-- .mcp_config::parse_mcp_servers (POS: per-server mcp.json variant parsing)
-- .models::PluginParseResult (POS: shared parser output dataclasses)
-- .rules::is_excluded_path (POS: shared path-exclusion rule)
-- backends.skills.scanning.zip_extract::safe_extract_zip (POS: secure archive extraction)

[OUTPUT]
-- AgentPluginParser.parse_zip: bytes → PluginParseResult with per-component
   failure isolation; never persists. ``PluginParseResult.files`` retains the
   non-skill file tree (plugin.json / mcp.json / bundled stdio scripts) so the
   business layer can persist bundled MCP servers on import.

[POS]
Framework-level, client-agnostic Agent Plugins 1.0.0 package parser (parse-only,
persistence owned by the business layer).
"""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import Any

from myrm_agent_harness.backends.skills.scanning.zip_extract import safe_extract_zip

from . import manifest, mcp_config
from .agents import discover_agents, discover_workspace_files
from .frontmatter import split_frontmatter
from .integrity import (
    verify_mcp_server_artifacts,
    verify_plugin_capability_diff,
)
from .manifest import decode_manifest_json, parse_manifest
from .mcp_config import decode_mcp_json, parse_mcp_servers
from .models import (
    PluginDiagnosticLevel,
    PluginParseResult,
    PluginSkill,
)
from .rules import is_excluded_path

logger = logging.getLogger(__name__)

# Build/VCS/platform leftovers that are never worth reporting as ignored files.
_NOISE_SEGMENTS = frozenset({".git", ".venv", "__pycache__", "node_modules", ".DS_Store", "__MACOSX"})
_MAX_REPORTED_IGNORED = 5


class AgentPluginParser:
    """Parse an Agent Plugins 1.0.0 ZIP into structured component records."""

    def parse_zip(self, zip_bytes: bytes) -> PluginParseResult:
        """Parse a plugin ZIP into skills, servers, and diagnostics.

        Raises:
            ArchiveSecurityError: archive-level security violation (Zip Bomb, size,
                entry-count, executable-binary, traversal, symlink). The caller maps
                this to a user-facing archive-security message.
        """
        ignored: list[str] = []

        def _skip_excluded(path: str) -> bool:
            if is_excluded_path(path):
                ignored.append(path)
                return True
            return False

        # safe_extract_zip enforces Zip Bomb / symlink / traversal / executable defenses.
        # strip_top_dir=True -> the plugin root becomes the archive's top-level directory.
        all_files = safe_extract_zip(zip_bytes, strip_top_dir=True, forbidden_check=_skip_excluded)
        result = self._parse_files(all_files)
        _report_ignored_files(result, ignored)
        return result

    def parse_files(self, all_files: dict[str, bytes]) -> PluginParseResult:
        """Parse uncompressed file mapping of an Agent Plugins package."""
        return self._parse_files(all_files)

    def _parse_files(self, all_files: dict[str, bytes]) -> PluginParseResult:
        result = PluginParseResult()

        # plugin.json is fatal to the whole plugin (§5.2).
        try:
            raw_manifest = self._load_plugin_manifest(all_files)
            if raw_manifest is None:
                result.add_diagnostic(
                    "plugin",
                    "manifest_missing",
                    "plugin.json is missing",
                    PluginDiagnosticLevel.ERROR,
                )
                return result
            meta, _ = parse_manifest(raw_manifest)
        except manifest.ManifestSchemaError as exc:
            result.add_diagnostic("plugin", "unsupported_schema", str(exc))
            return result
        except manifest.ManifestSchemaValidationError as exc:
            result.add_diagnostic("plugin", exc.code, str(exc))
            return result
        except manifest.ManifestParseError as exc:
            result.add_diagnostic("plugin", "manifest_invalid_json", str(exc))
            return result

        result.meta = meta
        result.schemas.append("https://agent-plugins.org/schemas/1.0.0/plugin.schema.json")

        # Retain every non-skill file (plugin.json / mcp.json / bundled stdio
        # scripts) so the business layer can persist them to the plugin root
        # directory on import. Skill files live on PluginSkill.files instead.
        result.files = {path: content for path, content in all_files.items() if not path.startswith("skills/")}

        # Skills discovery (§6.1, §7.1): non-recursive, SKILL.md gate.
        self._discover_skills(all_files, result)

        # MCP discovery (§6.1, §7.2): invalid mcp.json disables MCP only.
        self._discover_mcp(all_files, result)

        # Client-specific components: ``ai.myrm/`` namespace first, community layout as fallback.
        result.agents.extend(discover_agents(all_files, extensions=meta.extensions, raw_manifest=raw_manifest))
        result.workspace_files.update(discover_workspace_files(all_files))

        return result

    def _load_plugin_manifest(self, all_files: dict[str, bytes]) -> dict[str, Any] | None:
        raw = all_files.get("plugin.json")
        if raw is None:
            return None
        return decode_manifest_json(raw)

    def _discover_skills(self, all_files: dict[str, bytes], result: PluginParseResult) -> None:
        # Non-recursive: only immediate children of skills/ containing SKILL.md (§7.1).
        skill_names: set[str] = set()
        for path in all_files:
            if path.startswith("skills/") and path.endswith("/SKILL.md"):
                rest = path[len("skills/") :]
                skill_name = rest.removesuffix("/SKILL.md")
                if "/" in skill_name:
                    continue  # deeper than one level -> ignored (non-recursive)
                skill_names.add(skill_name)

        if not skill_names and not any(p.startswith("skills/") for p in all_files):
            return  # missing fixed location is not an error (§6.2)

        for name in sorted(skill_names):
            skill = self._build_skill(name, all_files)
            if skill is not None:
                result.skills.append(skill)
            else:
                result.add_diagnostic(
                    f"skill:{name}",
                    "skill_invalid",
                    f"Skill '{name}' is skipped",
                    PluginDiagnosticLevel.WARNING,
                )

    def _build_skill(self, name: str, all_files: dict[str, bytes]) -> PluginSkill | None:
        prefix = f"skills/{name}/"
        skill_files: dict[str, bytes] = {}
        for path, content in all_files.items():
            if path.startswith(prefix):
                skill_files[path[len(prefix) :]] = content

        if "SKILL.md" not in skill_files:
            return None

        skill_md = skill_files["SKILL.md"].decode("utf-8", errors="replace")
        metadata, description, pure_content = split_frontmatter(skill_md)
        return PluginSkill(
            name=name,
            description=description,
            content=pure_content,
            files=skill_files,
            metadata=metadata,
        )

    def _discover_mcp(self, all_files: dict[str, bytes], result: PluginParseResult) -> None:
        if "mcp.json" not in all_files:
            return  # missing fixed location is not an error (§6.2)

        try:
            raw = decode_mcp_json(all_files["mcp.json"])
            if raw is None:
                result.add_diagnostic("mcp", "mcp_missing", "mcp.json is not a JSON object")
                return
            plugin_schema = result.schemas[0] if result.schemas else None
            mcp_config.validate_mcp_top_level(raw, plugin_schema=plugin_schema)
        except mcp_config.McpConfigError as exc:
            result.add_diagnostic("mcp", exc.code, str(exc))
            return  # disable MCP for the plugin, keep skills (§7.2.2)

        parsed_servers = parse_mcp_servers(raw)
        package_file_set = frozenset(all_files.keys())
        has_ts_sources = any(k.endswith((".ts", ".tsx")) for k in package_file_set)

        for server in parsed_servers:
            is_valid, target_path, reason = verify_mcp_server_artifacts(
                server, package_file_set, has_ts_sources=has_ts_sources
            )
            raw_entry = target_path or ""
            missing_tuple = (raw_entry,) if (not is_valid and raw_entry) else ()
            updated_server = replace(
                server,
                is_runnable=is_valid,
                missing_artifact=target_path if not is_valid else None,
                missing_artifacts=missing_tuple,
            )
            result.servers.append(updated_server)

            if not is_valid:
                result.add_diagnostic(
                    f"mcp:{server.name}",
                    "mcp_missing_artifact",
                    reason or f"MCP server '{server.name}' references missing artifact '{target_path}'",
                    PluginDiagnosticLevel.ERROR,
                )

        # Surface skipped/invalid variants as diagnostics so failures are visible (§11.3).
        raw_servers = raw.get("mcpServers")
        if isinstance(raw_servers, dict):
            parsed_names = {s.name for s in result.servers}
            for name in raw_servers:
                if name not in parsed_names:
                    result.add_diagnostic(
                        f"mcp:{name}",
                        "mcp_invalid_server",
                        f"MCP server '{name}' is skipped",
                        PluginDiagnosticLevel.WARNING,
                    )

        # Audit declared capabilities against inferred server capabilities (Capability Diff)
        if result.meta and result.meta.declared_capabilities:
            diff_diags = verify_plugin_capability_diff(result.meta.declared_capabilities, result.servers)
            result.diagnostics.extend(diff_diags)


def _report_ignored_files(result: PluginParseResult, ignored: list[str]) -> None:
    """Surface hidden/build files dropped by the archive filter (excluding well-known noise)."""
    meaningful = [path for path in ignored if not any(part in _NOISE_SEGMENTS for part in path.split("/"))]
    if not meaningful:
        return
    shown = ", ".join(sorted(meaningful)[:_MAX_REPORTED_IGNORED])
    more = len(meaningful) - _MAX_REPORTED_IGNORED
    suffix = f" and {more} more" if more > 0 else ""
    result.add_diagnostic(
        "plugin",
        "files_ignored",
        f"{len(meaningful)} hidden files were not imported: {shown}{suffix}",
        PluginDiagnosticLevel.INFO,
    )
