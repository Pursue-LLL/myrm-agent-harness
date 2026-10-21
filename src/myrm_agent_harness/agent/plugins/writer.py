"""Agent Plugins 1.0.0 bundle writer — the strict inverse of ``AgentPluginParser``.

Everything the parser reads can be written here, and every package written here
is verified by parsing it back before it is returned (see roundtrip.py). The
writer never guesses: invalid names, excluded paths, oversized files and
non-portable MCP servers are rejected with a precise error instead of being
silently dropped, so what the caller asked to ship is exactly what ships.

Client-specific data (agent profiles, workspace templates, entry agent) is
written under the ``ai.myrm`` namespace (spec §8); ``plugin.json`` never gains
non-standard top-level fields.

[INPUT]
-- .models::PluginAgent / PluginMcpServer (POS: shared parser output dataclasses)
-- .rules::* (POS: name predicate, path exclusion, namespace layout, capacity ceilings)
-- .roundtrip::verify_bundle (POS: parse-back self-check)

[OUTPUT]
-- PluginBundleSpec: declarative description of one package.
-- build_plugin_bundle: spec → deterministic ZIP bytes (same input → same bytes).
-- PluginPackageResult / PluginBundleError: result and validation failure types.

[POS]
Framework-level, client-agnostic package writer. Zero persistence, zero LLM.
"""

from __future__ import annotations

import io
import json
import logging
import zipfile
from collections.abc import Mapping
from dataclasses import dataclass, field

import yaml

from .manifest import MCP_SCHEMA, PLUGIN_SCHEMA
from .models import PluginAgent, PluginMcpServer
from .rules import (
    AGENT_STRUCTURAL_KEYS,
    MAX_PLUGIN_ZIP_BYTES,
    MAX_TEMPLATE_FILE_BYTES,
    MAX_TOTAL_TEMPLATE_BYTES,
    MYRM_AGENTS_DIR,
    MYRM_NAMESPACE,
    MYRM_WORKSPACE_DIR,
    is_excluded_path,
    is_valid_plugin_name,
    plugin_identity,
)

logger = logging.getLogger(__name__)

SKILL_MD = "SKILL.md"
_ZIP_EPOCH = (1980, 1, 1, 0, 0, 0)
_FILE_MODE = 0o100644 << 16
_UNIX = 3


class PluginBundleError(ValueError):
    """The spec cannot be packaged as a conformant, importable plugin."""


@dataclass
class PluginPackageResult:
    """Outcome of building a plugin package."""

    success: bool
    zip_content: bytes | None
    filename: str | None
    error: str | None = None


@dataclass(frozen=True)
class PluginBundleSpec:
    """Declarative description of one plugin package.

    ``skills`` maps a skill directory name to its files. ``agents`` are written
    to ``ai.myrm/agents``; the entry agent is the one flagged ``is_entry_agent``
    (the first non-subagent when none is flagged). ``extensions`` carries extra
    client namespaces such as ``ai.myrm.skill``.
    """

    name: str
    version: str = "1.0.0"
    description: str = ""
    author_name: str = "Myrm User"
    keywords: tuple[str, ...] = ()
    skills: Mapping[str, Mapping[str, bytes]] = field(default_factory=dict)
    mcp_servers: tuple[PluginMcpServer, ...] = ()
    agents: tuple[PluginAgent, ...] = ()
    workspace_files: Mapping[str, bytes] = field(default_factory=dict)
    extensions: Mapping[str, Mapping[str, object]] = field(default_factory=dict)


def agent_slugs(agents: tuple[PluginAgent, ...]) -> list[str]:
    """Deterministic, unique file slug per agent (``plugin_identity`` + ``-N`` on collision)."""
    seen: dict[str, int] = {}
    slugs: list[str] = []
    for agent in agents:
        base = plugin_identity(agent.name, fallback="agent")
        seen[base] = seen.get(base, 0) + 1
        slugs.append(base if seen[base] == 1 else f"{base}-{seen[base]}")
    return slugs


def entry_agent_index(agents: tuple[PluginAgent, ...]) -> int | None:
    """Index of the entry agent: flagged one, else the first non-subagent, else the first."""
    if not agents:
        return None
    for index, agent in enumerate(agents):
        if agent.is_entry_agent:
            return index
    return next((i for i, a in enumerate(agents) if not a.is_subagent), 0)


def render_bundle_files(spec: PluginBundleSpec) -> dict[str, bytes]:
    """Render the spec into plugin-root-relative files (validated, not yet zipped)."""
    if not is_valid_plugin_name(spec.name):
        raise PluginBundleError(f"Invalid plugin name: {spec.name!r}")

    slugs = agent_slugs(spec.agents)
    entry_index = entry_agent_index(spec.agents)
    files: dict[str, bytes] = {
        "plugin.json": _render_manifest(spec, slugs[entry_index] if entry_index is not None else None)
    }
    if spec.mcp_servers:
        files["mcp.json"] = _render_mcp_json(spec.mcp_servers)

    for skill_name, skill_files in spec.skills.items():
        _put_skill(files, skill_name, skill_files)

    for agent, slug in zip(spec.agents, slugs, strict=True):
        files[f"{MYRM_AGENTS_DIR}/{slug}.md"] = _render_agent_markdown(agent)

    _put_workspace(files, spec.workspace_files)
    return files


def build_plugin_bundle(spec: PluginBundleSpec, *, verify: bool = True) -> PluginPackageResult:
    """Build a deterministic plugin ZIP and (by default) verify it by parsing it back."""
    try:
        files = render_bundle_files(spec)
        zip_content = _zip_files(spec.name, files)
        if len(zip_content) > MAX_PLUGIN_ZIP_BYTES:
            raise PluginBundleError(f"Package is {len(zip_content)} bytes, over the {MAX_PLUGIN_ZIP_BYTES} byte limit")
        if verify:
            from .roundtrip import verify_bundle

            verify_bundle(zip_content, spec)
    except PluginBundleError as exc:
        logger.warning("Plugin bundle rejected: %s (%s)", spec.name, exc)
        return PluginPackageResult(success=False, zip_content=None, filename=None, error=str(exc))

    filename = f"{spec.name}_v{spec.version or '1.0.0'}.zip"
    logger.info("Plugin bundle built: %s (%d bytes, %d files)", filename, len(zip_content), len(files))
    return PluginPackageResult(success=True, zip_content=zip_content, filename=filename)


def _render_manifest(spec: PluginBundleSpec, entry_slug: str | None) -> bytes:
    manifest: dict[str, object] = {
        "$schema": PLUGIN_SCHEMA,
        "name": spec.name,
        "version": spec.version or "1.0.0",
        "description": spec.description or f"Agent plugin {spec.name}",
    }
    if spec.author_name:
        manifest["author"] = {"name": spec.author_name}
    if spec.keywords:
        manifest["keywords"] = list(dict.fromkeys(spec.keywords))

    extensions = {namespace: dict(value) for namespace, value in spec.extensions.items()}
    if entry_slug is not None:
        extensions.setdefault(MYRM_NAMESPACE, {})["entryAgent"] = entry_slug
    if extensions:
        manifest["extensions"] = extensions
    return _json_bytes(manifest)


def _render_mcp_json(servers: tuple[PluginMcpServer, ...]) -> bytes:
    entries: dict[str, dict[str, object]] = {}
    for server in servers:
        if server.name in entries:
            raise PluginBundleError(f"Duplicate MCP server name: {server.name!r}")
        entries[server.name] = _mcp_entry(server)
    return _json_bytes({"$schema": MCP_SCHEMA, "mcpServers": entries})


def _mcp_entry(server: PluginMcpServer) -> dict[str, object]:
    if server.server_type == "stdio":
        entry: dict[str, object] = {"type": "stdio", "command": server.command}
        if server.args:
            entry["args"] = list(server.args)
        env = {key: server.raw_env.get(key, "") for key in dict.fromkeys([*server.env_key_names, *server.raw_env])}
        if env:
            entry["env"] = env
        if server.cwd:
            entry["cwd"] = server.cwd
        return entry

    entry = {"type": "sse" if server.server_type == "sse" else "streamable-http", "url": server.url}
    if server.headers:
        entry["headers"] = dict(server.headers)
    return entry


def _render_agent_markdown(agent: PluginAgent) -> bytes:
    header: dict[str, object] = {"name": agent.name}
    if agent.description:
        header["description"] = agent.description
    if agent.max_iterations is not None:
        header["max_iterations"] = agent.max_iterations
    for key, values in (
        ("skills", agent.skill_names),
        ("tools", agent.tool_names),
        ("mcps", agent.mcp_names),
        ("subagents", agent.subagent_names),
    ):
        if values:
            header[key] = list(values)
    if agent.is_subagent:
        header["is_subagent"] = True
    header.update({key: value for key, value in agent.metadata.items() if key not in AGENT_STRUCTURAL_KEYS})

    try:
        frontmatter = yaml.safe_dump(header, allow_unicode=True, sort_keys=False, width=1_000_000).rstrip("\n")
    except yaml.YAMLError as exc:
        raise PluginBundleError(f"Agent {agent.name!r} has non-serializable profile data: {exc}") from exc
    return f"---\n{frontmatter}\n---\n{agent.system_prompt.strip()}\n".encode()


def _put_skill(files: dict[str, bytes], skill_name: str, skill_files: Mapping[str, bytes]) -> None:
    if not skill_name or "/" in skill_name or is_excluded_path(skill_name):
        raise PluginBundleError(f"Invalid skill directory name: {skill_name!r}")
    if SKILL_MD not in skill_files:
        raise PluginBundleError(f"Skill {skill_name!r} has no {SKILL_MD}")
    for rel_path, content in skill_files.items():
        _check_relative_path(rel_path, f"skill {skill_name!r}")
        files[f"skills/{skill_name}/{rel_path}"] = content


def _put_workspace(files: dict[str, bytes], workspace_files: Mapping[str, bytes]) -> None:
    total = 0
    for rel_path, content in workspace_files.items():
        _check_relative_path(rel_path, "workspace")
        if len(content) > MAX_TEMPLATE_FILE_BYTES:
            raise PluginBundleError(f"Workspace file {rel_path!r} exceeds {MAX_TEMPLATE_FILE_BYTES} bytes")
        total += len(content)
        files[f"{MYRM_WORKSPACE_DIR}/{rel_path}"] = content
    if total > MAX_TOTAL_TEMPLATE_BYTES:
        raise PluginBundleError(f"Workspace files exceed {MAX_TOTAL_TEMPLATE_BYTES} bytes in total")


def _check_relative_path(rel_path: str, owner: str) -> None:
    parts = rel_path.split("/")
    if not rel_path or rel_path.startswith(("/", "\\")) or ".." in parts or "" in parts or "\\" in rel_path:
        raise PluginBundleError(f"Unsafe file path in {owner}: {rel_path!r}")
    if is_excluded_path(rel_path):
        raise PluginBundleError(f"Excluded file path in {owner}: {rel_path!r}")


def _zip_files(plugin_name: str, files: Mapping[str, bytes]) -> bytes:
    """Deterministic archive: sorted entries, fixed timestamps and permissions."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(files):
            info = zipfile.ZipInfo(f"{plugin_name}/{path}", date_time=_ZIP_EPOCH)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = _UNIX
            info.external_attr = _FILE_MODE
            archive.writestr(info, files[path])
    return buffer.getvalue()


def _json_bytes(payload: Mapping[str, object]) -> bytes:
    return json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")
