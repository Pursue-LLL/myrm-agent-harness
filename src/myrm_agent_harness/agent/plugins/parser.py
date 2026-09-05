"""Agent Plugins 1.0.0 package parser.

Orchestrates secure extraction and discovery with per-component failure isolation
(spec §6, §7, §11.3):
  - A fatal ``plugin.json`` violation rejects the whole plugin.
  - A bad skill is skipped; other skills and components still load.
  - A top-level ``mcp.json`` failure disables MCP; an invalid server variant is
    skipped; neither ever affects skills.

[INPUT]
-- .manifest::parse_manifest (POS: closed-schema plugin.json manifest validation)
-- .mcp_config::parse_mcp_servers (POS: per-server mcp.json variant parsing)
-- .models::PluginParseResult (POS: shared parser output dataclasses)
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
import re
from dataclasses import replace
from typing import Any

from myrm_agent_harness.backends.skills.scanning.zip_extract import safe_extract_zip

from . import manifest, mcp_config
from .integrity import verify_mcp_server_artifacts
from .manifest import decode_manifest_json, parse_manifest
from .mcp_config import decode_mcp_json, parse_mcp_servers
from .models import (
    PluginAgent,
    PluginDiagnosticLevel,
    PluginMcpServer,
    PluginParseResult,
    PluginSkill,
)

logger = logging.getLogger(__name__)

_EXCLUDED_SEGMENTS = frozenset(
    {".git", ".venv", "__pycache__", "node_modules", ".DS_Store", "__MACOSX"}
)


def _is_excluded_file(path: str) -> bool:
    parts = path.split("/")
    return any(part.startswith(".") or part in _EXCLUDED_SEGMENTS for part in parts)


class AgentPluginParser:
    """Parse an Agent Plugins 1.0.0 ZIP into structured component records."""

    def parse_zip(self, zip_bytes: bytes) -> PluginParseResult:
        """Parse a plugin ZIP into skills, servers, and diagnostics.

        Raises:
            ArchiveSecurityError: archive-level security violation (Zip Bomb, size,
                entry-count, executable-binary, traversal, symlink). The caller maps
                this to a user-facing archive-security message.
        """
        # safe_extract_zip enforces Zip Bomb / symlink / traversal / executable defenses.
        # strip_top_dir=True -> the plugin root becomes the archive's top-level directory.
        all_files = safe_extract_zip(
            zip_bytes,
            strip_top_dir=True,
            forbidden_check=_is_excluded_file,
        )
        return self._parse_files(all_files)

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
        result.schemas.append(
            "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"
        )

        # Retain every non-skill file (plugin.json / mcp.json / bundled stdio
        # scripts) so the business layer can persist them to the plugin root
        # directory on import. Skill files live on PluginSkill.files instead.
        result.files = {
            path: content
            for path, content in all_files.items()
            if not path.startswith("skills/")
        }

        # Skills discovery (§6.1, §7.1): non-recursive, SKILL.md gate.
        self._discover_skills(all_files, result)

        # MCP discovery (§6.1, §7.2): invalid mcp.json disables MCP only.
        self._discover_mcp(all_files, result)

        # Agent profiles discovery (WorkBuddy & community multi-agent layout).
        self._discover_agents(all_files, result, raw_manifest)

        # Prebuilt workspace template assets discovery.
        self._discover_workspace_files(all_files, result)

        return result

    def _load_plugin_manifest(
        self, all_files: dict[str, bytes]
    ) -> dict[str, Any] | None:
        raw = all_files.get("plugin.json")
        if raw is None:
            return None
        return decode_manifest_json(raw)

    def _discover_skills(
        self, all_files: dict[str, bytes], result: PluginParseResult
    ) -> None:
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

    def _build_skill(
        self, name: str, all_files: dict[str, bytes]
    ) -> PluginSkill | None:
        prefix = f"skills/{name}/"
        skill_files: dict[str, bytes] = {}
        for path, content in all_files.items():
            if path.startswith(prefix):
                skill_files[path[len(prefix) :]] = content

        if "SKILL.md" not in skill_files:
            return None

        skill_md = skill_files["SKILL.md"].decode("utf-8", errors="replace")
        metadata, description, pure_content = _parse_skill_frontmatter(skill_md)
        return PluginSkill(
            name=name,
            description=description,
            content=pure_content,
            files=skill_files,
            metadata=metadata,
        )

    def _discover_mcp(
        self, all_files: dict[str, bytes], result: PluginParseResult
    ) -> None:
        if "mcp.json" not in all_files:
            return  # missing fixed location is not an error (§6.2)

        try:
            raw = decode_mcp_json(all_files["mcp.json"])
            if raw is None:
                result.add_diagnostic(
                    "mcp", "mcp_missing", "mcp.json is not a JSON object"
                )
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

    def _discover_agents(
        self,
        all_files: dict[str, bytes],
        result: PluginParseResult,
        manifest_meta: dict[str, Any] | None,
    ) -> None:
        """Discover agents from `agents/*.md` or `agents/<name>/AGENT.md`."""
        agent_paths: dict[str, bytes] = {}
        for path, content in all_files.items():
            if path.startswith("agents/") and path.endswith(".md"):
                agent_paths[path] = content

        if not agent_paths:
            return

        entry_agent_hint: str | None = None
        if isinstance(manifest_meta, dict):
            raw_entry = manifest_meta.get("entry_agent") or manifest_meta.get(
                "main_agent"
            )
            if isinstance(raw_entry, str) and raw_entry.strip():
                entry_agent_hint = raw_entry.strip().lower()

        parsed_agents: list[PluginAgent] = []
        for path in sorted(agent_paths):
            content = agent_paths[path]
            text = content.decode("utf-8", errors="replace")
            metadata, description, prompt = _parse_skill_frontmatter(text)

            # Derive agent name
            rel_name = path[len("agents/") :]
            if rel_name.endswith("/AGENT.md"):
                agent_name = rel_name.removesuffix("/AGENT.md")
            elif rel_name.endswith(".md"):
                agent_name = rel_name.removesuffix(".md")
            else:
                continue

            display_name = str(metadata.get("name") or agent_name)
            metadata.setdefault("slug", agent_name)
            max_iters = metadata.get("max_iterations") or metadata.get("max_iters")
            parsed_iters = (
                int(max_iters)
                if isinstance(max_iters, (int, str)) and str(max_iters).isdigit()
                else None
            )

            # Subagents / Skills / Tools dependencies from metadata
            raw_skills = metadata.get("skills") or metadata.get("skill_names") or ()
            skill_tuple = (
                tuple(str(s) for s in raw_skills)
                if isinstance(raw_skills, (list, tuple))
                else ()
            )

            raw_tools = metadata.get("tools") or metadata.get("tool_names") or ()
            tool_tuple = (
                tuple(str(t) for t in raw_tools)
                if isinstance(raw_tools, (list, tuple))
                else ()
            )

            raw_mcps = metadata.get("mcps") or metadata.get("mcp_names") or ()
            mcp_tuple = (
                tuple(str(m) for m in raw_mcps)
                if isinstance(raw_mcps, (list, tuple))
                else ()
            )

            raw_subagents = (
                metadata.get("subagents") or metadata.get("subagent_names") or ()
            )
            subagent_tuple = (
                tuple(str(sa) for sa in raw_subagents)
                if isinstance(raw_subagents, (list, tuple))
                else ()
            )

            is_sub = bool(metadata.get("is_subagent", False))
            is_entry = False
            if entry_agent_hint:
                is_entry = (agent_name.lower() == entry_agent_hint) or (
                    display_name.lower() == entry_agent_hint
                )

            parsed_agents.append(
                PluginAgent(
                    name=display_name,
                    description=description or str(metadata.get("description", "")),
                    system_prompt=prompt,
                    max_iterations=parsed_iters,
                    skill_names=skill_tuple,
                    tool_names=tool_tuple,
                    mcp_names=mcp_tuple,
                    subagent_names=subagent_tuple,
                    is_subagent=is_sub,
                    is_entry_agent=is_entry,
                    metadata=metadata,
                )
            )

        # If no explicit entry agent was marked and we have multiple agents, mark the first or root one as entry
        if parsed_agents and not any(a.is_entry_agent for a in parsed_agents):
            first = parsed_agents[0]
            parsed_agents[0] = PluginAgent(
                name=first.name,
                description=first.description,
                system_prompt=first.system_prompt,
                max_iterations=first.max_iterations,
                skill_names=first.skill_names,
                tool_names=first.tool_names,
                mcp_names=first.mcp_names,
                subagent_names=first.subagent_names,
                is_subagent=False,
                is_entry_agent=True,
                metadata=first.metadata,
            )

        result.agents.extend(parsed_agents)

    def _discover_workspace_files(
        self,
        all_files: dict[str, bytes],
        result: PluginParseResult,
    ) -> None:
        """Discover bundled workspace template files under `workspace/` or `template_files/`."""
        for path, content in all_files.items():
            if path.startswith("workspace/"):
                rel_path = path[len("workspace/") :]
                if rel_path:
                    result.workspace_files[rel_path] = content
            elif path.startswith("template_files/"):
                rel_path = path[len("template_files/") :]
                if rel_path:
                    result.workspace_files[rel_path] = content


def _parse_skill_frontmatter(text: str) -> tuple[dict[str, Any], str, str]:
    """Split SKILL.md frontmatter (``---`` delimited YAML) from body, returning
    (metadata, description, pure_content)."""
    import yaml

    match = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
    if not match:
        return {}, "", text.strip()

    pure_content = text[match.end() :].strip()
    metadata: dict[str, Any] = {}
    description = ""
    try:
        frontmatter = yaml.safe_load(match.group(1))
        if isinstance(frontmatter, dict):
            metadata = frontmatter
            raw_description = frontmatter.get("description")
            description = raw_description if isinstance(raw_description, str) else ""
    except Exception as exc:  # frontmatter parse failure -> treat as pure content
        logger.warning("Failed to parse skill frontmatter: %s", exc)
        return {}, "", text.strip()
    return metadata, description, pure_content
