"""Agent profile and workspace-template discovery for Agent Plugins packages.

Agent profiles and workspace templates are client-specific data, so the
canonical location is the ``ai.myrm`` namespace (spec §8): ``ai.myrm/agents/``,
``ai.myrm/workspace/`` and ``extensions["ai.myrm"]`` in plugin.json. The
community top-level layout (``agents/``, ``workspace/``, ``template_files/``,
top-level ``entry_agent``) is accepted for inbound packages only; the namespaced
location wins whenever both are present.

[INPUT]
-- .frontmatter::split_frontmatter (POS: markdown frontmatter split)
-- .models::PluginAgent (POS: shared parser output dataclasses)
-- .rules::MYRM_* (POS: namespace layout constants)

[OUTPUT]
-- discover_agents: archive files → PluginAgent records (entry agent resolved).
-- discover_workspace_files: archive files → workspace template relative paths.

[POS]
Inbound discovery of client-specific components; the inverse lives in writer.py.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace

from .frontmatter import split_frontmatter
from .models import PluginAgent
from .rules import MYRM_AGENTS_DIR, MYRM_NAMESPACE, MYRM_WORKSPACE_DIR

_COMMUNITY_AGENTS_DIR = "agents"
_COMMUNITY_WORKSPACE_DIRS = ("workspace", "template_files")


def discover_agents(
    all_files: Mapping[str, bytes],
    *,
    extensions: Mapping[str, Mapping[str, object]],
    raw_manifest: Mapping[str, object],
) -> list[PluginAgent]:
    """Discover agent profiles; the first one becomes the entry when none is declared."""
    agent_files = _collect_agent_files(all_files, MYRM_AGENTS_DIR) or _collect_agent_files(
        all_files, _COMMUNITY_AGENTS_DIR
    )
    if not agent_files:
        return []

    entry_hint = _entry_agent_hint(extensions, raw_manifest)
    agents = [_build_agent(slug, content, entry_hint) for slug, content in agent_files]
    if not any(agent.is_entry_agent for agent in agents):
        agents[0] = replace(agents[0], is_subagent=False, is_entry_agent=True)
    return agents


def discover_workspace_files(all_files: Mapping[str, bytes]) -> dict[str, bytes]:
    """Discover bundled workspace template files (relative path → content)."""
    namespaced = _files_under(all_files, (f"{MYRM_WORKSPACE_DIR}/",))
    return namespaced or _files_under(all_files, tuple(f"{d}/" for d in _COMMUNITY_WORKSPACE_DIRS))


def _files_under(all_files: Mapping[str, bytes], prefixes: tuple[str, ...]) -> dict[str, bytes]:
    found: dict[str, bytes] = {}
    for path, content in all_files.items():
        for prefix in prefixes:
            if path.startswith(prefix) and len(path) > len(prefix):
                found[path[len(prefix) :]] = content
                break
    return found


def _collect_agent_files(all_files: Mapping[str, bytes], directory: str) -> list[tuple[str, bytes]]:
    """Return ``(slug, content)`` for ``<dir>/<slug>.md`` and ``<dir>/<slug>/AGENT.md``, sorted by path."""
    prefix = f"{directory}/"
    collected: list[tuple[str, bytes]] = []
    for path in sorted(all_files):
        if not path.startswith(prefix) or not path.endswith(".md"):
            continue
        rel = path[len(prefix) :]
        slug = rel.removesuffix("/AGENT.md") if rel.endswith("/AGENT.md") else rel.removesuffix(".md")
        if slug:
            collected.append((slug, all_files[path]))
    return collected


def _entry_agent_hint(extensions: Mapping[str, Mapping[str, object]], raw_manifest: Mapping[str, object]) -> str | None:
    namespaced = extensions.get(MYRM_NAMESPACE, {}).get("entryAgent")
    for candidate in (namespaced, raw_manifest.get("entry_agent"), raw_manifest.get("main_agent")):
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip().lower()
    return None


def _build_agent(slug: str, content: bytes, entry_hint: str | None) -> PluginAgent:
    metadata, description, prompt = split_frontmatter(content.decode("utf-8", errors="replace"))
    display_name = str(metadata.get("name") or slug)
    metadata.setdefault("slug", slug)

    raw_iters = metadata.get("max_iterations") or metadata.get("max_iters")
    max_iterations = int(raw_iters) if isinstance(raw_iters, (int, str)) and str(raw_iters).isdigit() else None

    return PluginAgent(
        name=display_name,
        description=description or str(metadata.get("description", "")),
        system_prompt=prompt,
        max_iterations=max_iterations,
        skill_names=_names(metadata, "skills", "skill_names"),
        tool_names=_names(metadata, "tools", "tool_names"),
        mcp_names=_names(metadata, "mcps", "mcp_names"),
        subagent_names=_names(metadata, "subagents", "subagent_names"),
        is_subagent=bool(metadata.get("is_subagent", False)),
        is_entry_agent=entry_hint is not None and entry_hint in (slug.lower(), display_name.lower()),
        metadata=metadata,
    )


def _names(metadata: Mapping[str, object], *keys: str) -> tuple[str, ...]:
    raw = next((metadata[key] for key in keys if metadata.get(key)), ())
    return tuple(str(item) for item in raw) if isinstance(raw, (list, tuple)) else ()
