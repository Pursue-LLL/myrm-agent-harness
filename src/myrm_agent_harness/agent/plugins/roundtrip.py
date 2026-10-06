"""Parse-back verification for packages produced by the bundle writer.

A package is only handed out when ``AgentPluginParser`` reads back exactly what
the spec described. This turns every writer/parser asymmetry (quoting, naming,
excluded paths, archive limits, MCP variants) into a build-time error instead of
a broken import on the receiving side.

[INPUT]
-- .parser::AgentPluginParser (POS: the authoritative reader)
-- .writer::PluginBundleSpec / PluginBundleError (POS: spec + failure type)

[OUTPUT]
-- verify_bundle: raises PluginBundleError when the parsed package differs from the spec.

[POS]
Internal self-check of the writer; no I/O beyond parsing the given bytes.
"""

from __future__ import annotations

from collections.abc import Mapping

from .models import PluginAgent, PluginDiagnosticLevel, PluginMcpServer, PluginParseResult
from .parser import AgentPluginParser
from .writer import PluginBundleError, PluginBundleSpec, agent_slugs, entry_agent_index

_MAX_REPORTED_PROBLEMS = 5


def verify_bundle(zip_bytes: bytes, spec: PluginBundleSpec) -> None:
    """Parse ``zip_bytes`` and compare every component with ``spec``."""
    try:
        parsed = AgentPluginParser().parse_zip(zip_bytes)
    except Exception as exc:  # archive-level security errors surface as importability failures
        raise PluginBundleError(f"Package cannot be re-imported: {exc}") from exc

    problems = _find_problems(parsed, spec)
    if problems:
        raise PluginBundleError("Package self-check failed: " + "; ".join(problems[:_MAX_REPORTED_PROBLEMS]))


def _find_problems(parsed: PluginParseResult, spec: PluginBundleSpec) -> list[str]:
    if parsed.meta is None:
        return ["plugin.json is not readable: " + "; ".join(d.message for d in parsed.diagnostics)]

    problems = [f"{d.component}: {d.message}" for d in parsed.diagnostics if d.level is not PluginDiagnosticLevel.INFO]
    if parsed.meta.name != spec.name:
        problems.append(f"plugin name changed to {parsed.meta.name!r}")

    problems += _compare_skills(parsed, spec)
    problems += _compare_servers(parsed.servers, spec.mcp_servers)
    problems += _compare_agents(parsed.agents, spec)
    if parsed.workspace_files != dict(spec.workspace_files):
        problems.append("workspace files differ")
    return problems


def _compare_skills(parsed: PluginParseResult, spec: PluginBundleSpec) -> list[str]:
    by_name = {skill.name: skill for skill in parsed.skills}
    if set(by_name) != set(spec.skills):
        return [f"skills differ: expected {sorted(spec.skills)}, parsed {sorted(by_name)}"]
    return [f"skill {name!r} files differ" for name, files in spec.skills.items() if dict(files) != by_name[name].files]


def _server_view(server: PluginMcpServer) -> tuple[object, ...]:
    return (
        server.server_type,
        server.command,
        tuple(server.args or ()),
        server.url,
        tuple(sorted((server.headers or {}).items())),
        tuple(sorted({key: server.raw_env.get(key, "") for key in (*server.env_key_names, *server.raw_env)}.items())),
        server.cwd,
    )


def _compare_servers(parsed: list[PluginMcpServer], expected: tuple[PluginMcpServer, ...]) -> list[str]:
    parsed_by_name = {server.name: server for server in parsed}
    problems: list[str] = []
    if set(parsed_by_name) != {server.name for server in expected}:
        return [f"MCP servers differ: expected {sorted(s.name for s in expected)}, parsed {sorted(parsed_by_name)}"]
    for server in expected:
        if _server_view(parsed_by_name[server.name]) != _server_view(server):
            problems.append(f"MCP server {server.name!r} changed")
    return problems


def _agent_view(agent: PluginAgent) -> tuple[object, ...]:
    return (
        agent.name,
        agent.description,
        agent.system_prompt.strip(),
        agent.max_iterations,
        agent.skill_names,
        agent.tool_names,
        agent.mcp_names,
        agent.subagent_names,
        agent.is_subagent,
    )


def _compare_agents(parsed: list[PluginAgent], spec: PluginBundleSpec) -> list[str]:
    if len(parsed) != len(spec.agents):
        return [f"agent count differs: expected {len(spec.agents)}, parsed {len(parsed)}"]

    slugs = agent_slugs(spec.agents)
    expected_by_slug: Mapping[str, PluginAgent] = dict(zip(slugs, spec.agents, strict=True))
    problems: list[str] = []
    for agent in parsed:
        original = expected_by_slug.get(str(agent.metadata.get("slug")))
        if original is None:
            problems.append(f"unexpected agent {agent.name!r}")
        elif _agent_view(agent) != _agent_view(original):
            problems.append(f"agent {original.name!r} changed")

    entry_index = entry_agent_index(spec.agents)
    entries = [agent.name for agent in parsed if agent.is_entry_agent]
    if entry_index is not None and entries != [spec.agents[entry_index].name]:
        problems.append(f"entry agent changed to {entries}")
    return problems
