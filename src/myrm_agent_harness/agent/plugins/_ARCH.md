# agent/plugins/

## Overview
Agent Plugins 1.0.0 standard parser — a framework-level, client-agnostic tool that
resolves the portable plugin package model (https://agent-plugins.org/schemas/1.0.0)
into structured component records for skills and MCP servers.

This module ONLY **parses and validates** plugin packages. It does NOT persist
anything. Persistence (SkillStore install, global `mcpServers` config, Agent profile
binding) is owned by the business layer (`myrm-agent-server`), which consumes the
[DATA](#output) records below.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Agent Plugins parsing & exporting module. | ✅ |
| `manifest.py` | Core | `AgentPluginManifest` + strict spec 1.0.0 validation (closed schema, name constraints, `$schema` version negotiation). | ✅ |
| `mcp_config.py` | Core | `AgentPluginMcpConfig` + per-server variant parsing (stdio / streamable-http / sse), placeholder scanning and containment. | ✅ |
| `parser.py` | Core | `AgentPluginParser.parse_zip` orchestrating discovery (skills/, agents/, mcp.json, workspace/ assets) with per-component failure isolation. Retains non-skill files on `PluginParseResult.files` for the business layer to persist into the plugin root; parses `PluginAgent` records and extracts `workspace_files`. | ✅ |
| `exporter.py` | Core | `AgentPluginPacker` + `canonical_plugin_name` building spec 1.0.0 conformant plugin ZIPs (`plugin.json` + `skills/<name>/` + optional `mcp.json`). | ✅ |
| `models.py` | Core | Shared dataclasses: `PluginCapabilityTier` (sandbox capability levels: read_only, fs_read, fs_write, network, shell_exec, destructive), `PluginSkill`, `PluginAgent`, `PluginMcpServer`, `PluginDiagnostic`, `PluginParseResult` (incl. `agents`, `workspace_files`, `aggregated_capabilities`, and non-skill `files`). | ✅ |
| `integrity.py` | Core | `verify_plugin_packaging_integrity`, `verify_mcp_server_artifacts`, & `infer_server_capabilities` ensuring stdio servers verify referenced build artifacts/entrypoints and infer granular sandbox capability tiers at parse time (prevents subprocess crashes on unbuilt packages and enforces zero-trust permissions). | ✅ |

## I/O

[PARSE]
- zip bytes → safe_extract_zip (framework `backends.skills.scanning`)
- plugin.json (root) → strict manifest validation
- skills/ (fixed location, non-recursive SKILL.md gate)
- mcp.json (root) → per-server variant validation

[OUTPUT]
- `PluginParseResult` (meta + skills + servers + diagnostics) — business layer consumes
  this to install skills and MCP servers and to surface component-level diagnostics.

## Key Dependencies

- `backends.skills.scanning.zip_extract::safe_extract_zip` — secure extraction.
- `backends.skills.scanning.archive_security` — typed archive security errors.
- `backends.skills.types_enums` — `SkillTrust` (business maps INSTALLED trust layer).

## Design Principles (spec-conformant)

1. **Version negotiation**: recognize exact canonical `$schema` IDs; never fetch a
   schema at load time; reject unsupported versions (fatal to the plugin).
2. **Closed schema**: unknown top-level `plugin.json` fields and non-object
   `extensions` are non-fatal; any other manifest violation is fatal.
3. **Localized failures**: a bad skill is skipped; invalid/MCP-mismatched `mcp.json`
   disables MCP for the plugin but never other components; per-server variants isolate.
4. **No persistence / no LLM** — pure offline parse.
