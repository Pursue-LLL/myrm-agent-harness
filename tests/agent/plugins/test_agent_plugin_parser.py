"""Agent Plugins 1.0.0 parser unit tests.

Covers manifest validation, mcp.json parsing, skills discovery, and
per-component failure isolation (§6, §7, §11.3 of the spec).
"""

from __future__ import annotations

import io
import json
import zipfile

import pytest

from myrm_agent_harness.agent.plugins.manifest import (
    ManifestNoSchemaError,
    ManifestParseError,
    ManifestSchemaValidationError,
    decode_manifest_json,
    parse_manifest,
)
from myrm_agent_harness.agent.plugins.mcp_config import (
    McpConfigError,
    has_placeholders,
    parse_mcp_servers,
    validate_mcp_top_level,
)
from myrm_agent_harness.agent.plugins.models import PluginDiagnosticLevel
from myrm_agent_harness.agent.plugins.parser import AgentPluginParser

PLUGIN_SCHEMA = "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"
MCP_SCHEMA = "https://agent-plugins.org/schemas/1.0.0/mcp.schema.json"


def build_plugin_zip(entries: dict[str, str], top_dir: str = "demo-plugin") -> bytes:
    """Build a plugin ZIP from a dict of relative paths to text content."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for rel_path, content in entries.items():
            zf.writestr(f"{top_dir}/{rel_path}", content)
    return buf.getvalue()


def default_plugin_json() -> str:
    return json.dumps(
        {
            "$schema": PLUGIN_SCHEMA,
            "name": "demo-plugin",
            "version": "1.0.0",
            "description": "A demo plugin",
        }
    )


# ---------------------------------------------------------------------------
# Manifest validation
# ---------------------------------------------------------------------------


class TestManifest:
    def test_valid_manifest(self) -> None:
        meta, reported = parse_manifest(
            json.loads(
                json.dumps(
                    {
                        "$schema": PLUGIN_SCHEMA,
                        "name": "my-plugin",
                        "version": "0.1.0",
                        "author": {"name": "Acme"},
                        "keywords": ["report", "pdf"],
                    }
                )
            )
        )
        assert meta.name == "my-plugin"
        assert meta.version == "0.1.0"
        assert meta.author == {"name": "Acme"}
        assert meta.keywords == ("report", "pdf")
        assert reported == []

    def test_unknown_top_level_field_reported_ignored(self) -> None:
        raw = json.loads(
            json.dumps(
                {
                    "$schema": PLUGIN_SCHEMA,
                    "name": "my-plugin",
                    "extensionCustomField": {"anything": 1},
                }
            )
        )
        meta, reported = parse_manifest(raw)
        assert meta.name == "my-plugin"
        assert any(entry["field"] == "extensionCustomField" for entry in reported)

    def test_non_object_extensions_reported_ignored(self) -> None:
        raw = json.loads(
            json.dumps(
                {"$schema": PLUGIN_SCHEMA, "name": "my-plugin", "extensions": "oops"}
            )
        )
        meta, reported = parse_manifest(raw)
        assert meta.name == "my-plugin"
        assert any(entry["field"] == "extensions" for entry in reported)

    def test_extension_namespace_must_be_object(self) -> None:
        raw = json.loads(
            json.dumps(
                {
                    "$schema": PLUGIN_SCHEMA,
                    "name": "my-plugin",
                    "extensions": {"com.example": "not-an-object"},
                }
            )
        )
        with pytest.raises(ManifestSchemaValidationError):
            parse_manifest(raw)

    def test_missing_schema_is_fatal(self) -> None:
        raw = json.loads(json.dumps({"name": "my-plugin"}))
        with pytest.raises(ManifestNoSchemaError):
            parse_manifest(raw)

    def test_invalid_name_rejected(self) -> None:
        raw = json.loads(json.dumps({"$schema": PLUGIN_SCHEMA, "name": "Bad_Name!"}))
        with pytest.raises(ManifestSchemaValidationError):
            parse_manifest(raw)

    def test_missing_name_rejected(self) -> None:
        raw = json.loads(json.dumps({"$schema": PLUGIN_SCHEMA}))
        with pytest.raises(ManifestSchemaValidationError):
            parse_manifest(raw)

    def test_keywords_must_be_string_list(self) -> None:
        raw = json.loads(
            json.dumps({"$schema": PLUGIN_SCHEMA, "name": "ok", "keywords": [1, 2]})
        )
        with pytest.raises(ManifestSchemaValidationError):
            parse_manifest(raw)

    def test_decode_manifest_json_rejects_non_object(self) -> None:
        with pytest.raises(ManifestParseError):
            decode_manifest_json(b"[1, 2, 3]")
        with pytest.raises(ManifestParseError):
            decode_manifest_json(b"not json")

    def test_decode_manifest_json_tolerates_bom(self) -> None:
        raw = b'\xef\xbb\xbf{"$schema": "%s", "name": "ok"}' % PLUGIN_SCHEMA.encode()
        assert decode_manifest_json(raw)["name"] == "ok"


# ---------------------------------------------------------------------------
# mcp.json parsing
# ---------------------------------------------------------------------------


class TestMcpConfig:
    def test_validate_top_level_ok(self) -> None:
        raw = json.loads(json.dumps({"$schema": MCP_SCHEMA, "mcpServers": {}}))
        validate_mcp_top_level(raw, plugin_schema=PLUGIN_SCHEMA)

    def test_validate_rejects_unknown_field(self) -> None:
        raw = json.loads(
            json.dumps({"$schema": MCP_SCHEMA, "mcpServers": {}, "extra": 1})
        )
        with pytest.raises(McpConfigError):
            validate_mcp_top_level(raw, plugin_schema=PLUGIN_SCHEMA)

    def test_validate_rejects_mcp_missing(self) -> None:
        raw = json.loads(json.dumps({"$schema": MCP_SCHEMA}))
        with pytest.raises(McpConfigError):
            validate_mcp_top_level(raw, plugin_schema=PLUGIN_SCHEMA)

    def test_validate_rejects_version_mismatch(self) -> None:
        raw = json.loads(json.dumps({"$schema": MCP_SCHEMA, "mcpServers": {}}))
        other_plugin_schema = (
            "https://agent-plugins.org/schemas/0.9.0/plugin.schema.json"
        )
        with pytest.raises(McpConfigError) as exc:
            validate_mcp_top_level(raw, plugin_schema=other_plugin_schema)
        assert exc.value.code == "mcp_version_mismatch"

    def test_stdio_server_parsed(self) -> None:
        raw = json.loads(
            json.dumps(
                {
                    "$schema": MCP_SCHEMA,
                    "mcpServers": {
                        "pdf": {
                            "type": "stdio",
                            "command": "./bin/server",
                            "args": ["--data", "${PLUGIN_DATA}/pdf"],
                            "cwd": "${PLUGIN_ROOT}",
                            "env": {"API_TOKEN": "secret-value"},
                        }
                    },
                }
            )
        )
        servers = parse_mcp_servers(raw)
        assert len(servers) == 1
        server = servers[0]
        assert server.name == "pdf"
        assert server.server_type == "stdio"
        assert server.command == "./bin/server"
        assert server.args == ["--data", "${PLUGIN_DATA}/pdf"]
        assert server.cwd == "${PLUGIN_ROOT}"
        assert server.env_key_names == ["API_TOKEN"]
        assert server.raw_env == {"API_TOKEN": "secret-value"}

    def test_stdio_reserved_env_rejected(self) -> None:
        raw = json.loads(
            json.dumps(
                {
                    "$schema": MCP_SCHEMA,
                    "mcpServers": {
                        "bad": {
                            "type": "stdio",
                            "command": "node",
                            "env": {"PLUGIN_ROOT": "/x"},
                        }
                    },
                }
            )
        )
        assert parse_mcp_servers(raw) == []

    def test_stdio_traversal_path_rejected(self) -> None:
        raw = json.loads(
            json.dumps(
                {
                    "$schema": MCP_SCHEMA,
                    "mcpServers": {
                        "escape": {"type": "stdio", "command": "../outside"},
                    },
                }
            )
        )
        assert parse_mcp_servers(raw) == []

    def test_stdio_absolute_command_rejected(self) -> None:
        raw = json.loads(
            json.dumps(
                {
                    "$schema": MCP_SCHEMA,
                    "mcpServers": {
                        "abs": {"type": "stdio", "command": "/usr/bin/node"},
                    },
                }
            )
        )
        assert parse_mcp_servers(raw) == []

    def test_stdio_shell_string_rejected(self) -> None:
        raw = json.loads(
            json.dumps(
                {
                    "$schema": MCP_SCHEMA,
                    "mcpServers": {
                        "sh": {"type": "stdio", "command": "node --version"},
                    },
                }
            )
        )
        assert parse_mcp_servers(raw) == []

    def test_remote_https_parsed(self) -> None:
        raw = json.loads(
            json.dumps(
                {
                    "$schema": MCP_SCHEMA,
                    "mcpServers": {
                        "api": {
                            "type": "streamable-http",
                            "url": "https://api.example.com/mcp",
                            "headers": {"X-Key": "value", "x-key2": "v2"},
                        }
                    },
                }
            )
        )
        servers = parse_mcp_servers(raw)
        assert len(servers) == 1
        assert servers[0].server_type == "streamable_http"
        assert servers[0].url == "https://api.example.com/mcp"
        assert servers[0].headers == {"X-Key": "value", "x-key2": "v2"}

    def test_remote_sse_parsed(self) -> None:
        raw = json.loads(
            json.dumps(
                {
                    "$schema": MCP_SCHEMA,
                    "mcpServers": {
                        "events": {"type": "sse", "url": "https://api.example.com/sse"},
                    },
                }
            )
        )
        servers = parse_mcp_servers(raw)
        assert len(servers) == 1
        assert servers[0].server_type == "sse"

    def test_remote_http_non_loopback_rejected(self) -> None:
        raw = json.loads(
            json.dumps(
                {
                    "$schema": MCP_SCHEMA,
                    "mcpServers": {
                        "insecure": {
                            "type": "streamable-http",
                            "url": "http://api.example.com/mcp",
                        },
                    },
                }
            )
        )
        assert parse_mcp_servers(raw) == []

    def test_remote_loopback_http_allowed(self) -> None:
        raw = json.loads(
            json.dumps(
                {
                    "$schema": MCP_SCHEMA,
                    "mcpServers": {
                        "local": {
                            "type": "streamable-http",
                            "url": "http://localhost:8080/mcp",
                        },
                    },
                }
            )
        )
        assert len(parse_mcp_servers(raw)) == 1

    def test_remote_userinfo_rejected(self) -> None:
        raw = json.loads(
            json.dumps(
                {
                    "$schema": MCP_SCHEMA,
                    "mcpServers": {
                        "auth": {
                            "type": "streamable-http",
                            "url": "https://user:pass@api.example.com/mcp",
                        },
                    },
                }
            )
        )
        assert parse_mcp_servers(raw) == []

    def test_remote_fragment_rejected(self) -> None:
        raw = json.loads(
            json.dumps(
                {
                    "$schema": MCP_SCHEMA,
                    "mcpServers": {
                        "frag": {
                            "type": "streamable-http",
                            "url": "https://api.example.com/mcp#section",
                        },
                    },
                }
            )
        )
        assert parse_mcp_servers(raw) == []

    def test_duplicate_case_insensitive_headers_rejected(self) -> None:
        raw = json.loads(
            json.dumps(
                {
                    "$schema": MCP_SCHEMA,
                    "mcpServers": {
                        "dup": {
                            "type": "streamable-http",
                            "url": "https://api.example.com/mcp",
                            "headers": {"X-Key": "a", "x-key": "b"},
                        },
                    },
                }
            )
        )
        assert parse_mcp_servers(raw) == []

    def test_unknown_server_type_skipped(self) -> None:
        raw = json.loads(
            json.dumps(
                {
                    "$schema": MCP_SCHEMA,
                    "mcpServers": {"weird": {"type": "websocket", "url": "wss://x"}},
                }
            )
        )
        assert parse_mcp_servers(raw) == []

    def test_has_placeholders(self) -> None:
        assert has_placeholders("${PLUGIN_ROOT}/bin")
        assert has_placeholders(None, "${PLUGIN_DATA}/x")
        assert not has_placeholders("plain", "value")


# ---------------------------------------------------------------------------
# Full package parsing (failure isolation)
# ---------------------------------------------------------------------------


class TestAgentPluginParser:
    def test_full_plugin_parse(self) -> None:
        zip_bytes = build_plugin_zip(
            {
                "plugin.json": default_plugin_json(),
                "skills/summarize/SKILL.md": "---\nname: summarize\ndescription: Do summaries\n---\nWork.",
                "skills/summarize/scripts/run.sh": "#!/bin/sh\necho hi",
                "mcp.json": json.dumps(
                    {
                        "$schema": MCP_SCHEMA,
                        "mcpServers": {
                            "pdf": {"type": "stdio", "command": "./bin/pdf"},
                        },
                    }
                ),
            }
        )
        result = AgentPluginParser().parse_zip(zip_bytes)
        assert result.meta is not None
        assert result.meta.name == "demo-plugin"
        assert len(result.skills) == 1
        assert result.skills[0].name == "summarize"
        assert (
            result.skills[0].files["SKILL.md"]
            == result.skills[0].skill_md_content.encode()
        )
        assert len(result.servers) == 1
        assert result.servers[0].name == "pdf"
        assert result.diagnostics == []

    def test_skill_files_are_scoped_to_skill_dir(self) -> None:
        zip_bytes = build_plugin_zip(
            {
                "plugin.json": default_plugin_json(),
                "skills/a/SKILL.md": "---\n---\nA.",
                "skills/a/tools/t.py": "x = 1",
                "skills/b/SKILL.md": "---\n---\nB.",
            }
        )
        result = AgentPluginParser().parse_zip(zip_bytes)
        by_name = {s.name: s for s in result.skills}
        assert set(by_name["a"].files.keys()) == {"SKILL.md", "tools/t.py"}
        assert set(by_name["b"].files.keys()) == {"SKILL.md"}

    def test_nested_skills_ignored(self) -> None:
        zip_bytes = build_plugin_zip(
            {
                "plugin.json": default_plugin_json(),
                "skills/top/SKILL.md": "---\n---\nTop.",
                "skills/top/nested/SKILL.md": "---\n---\nNested.",
            }
        )
        result = AgentPluginParser().parse_zip(zip_bytes)
        assert [s.name for s in result.skills] == ["top"]

    def test_invalid_skill_frontmatter_keeps_raw_content(self) -> None:
        # A skill whose frontmatter fails to parse degrades gracefully: the skill
        # is still installed with its raw content and empty metadata.
        zip_bytes = build_plugin_zip(
            {
                "plugin.json": default_plugin_json(),
                "skills/valid/SKILL.md": "---\nname: valid\n---\nOK.",
                "skills/broken/SKILL.md": "---\n  unparseable: [\n---\nBody.",
            }
        )
        result = AgentPluginParser().parse_zip(zip_bytes)
        by_name = {s.name: s for s in result.skills}
        assert set(by_name.keys()) == {"valid", "broken"}
        assert by_name["valid"].content == "OK."
        assert by_name["valid"].metadata == {"name": "valid"}
        assert by_name["broken"].metadata == {}
        assert by_name["broken"].content.startswith("---")

    def test_empty_description_frontmatter_normalized_to_empty_string(self) -> None:
        # ``description:`` with no value must parse as "" instead of the string
        # "None", so previews and persisted SkillRecords never show a literal
        # "None" description.
        zip_bytes = build_plugin_zip(
            {
                "plugin.json": default_plugin_json(),
                "skills/terse/SKILL.md": "---\nname: terse\ndescription:\n---\nTerse.",
                "skills/empty/SKILL.md": "---\nname: empty\ndescription: ~\n---\nEmpty.",
            }
        )
        result = AgentPluginParser().parse_zip(zip_bytes)
        by_name = {s.name: s for s in result.skills}
        assert by_name["terse"].description == ""
        assert by_name["empty"].description == ""
        assert by_name["terse"].metadata["description"] is None

    def test_missing_plugin_json_fatal(self) -> None:
        zip_bytes = build_plugin_zip({"skills/a/SKILL.md": "---\n---\nA."})
        result = AgentPluginParser().parse_zip(zip_bytes)
        assert result.meta is None
        assert result.skills == []
        assert any(d.code == "manifest_missing" for d in result.diagnostics)

    def test_invalid_plugin_json_fatal(self) -> None:
        zip_bytes = build_plugin_zip({"plugin.json": "not json at all"})
        result = AgentPluginParser().parse_zip(zip_bytes)
        assert result.meta is None
        assert any(d.code == "manifest_invalid_json" for d in result.diagnostics)

    def test_unsupported_schema_fatal(self) -> None:
        zip_bytes = build_plugin_zip(
            {
                "plugin.json": json.dumps(
                    {
                        "$schema": "https://agent-plugins.org/schemas/0.1.0/plugin.schema.json",
                        "name": "x",
                    }
                )
            }
        )
        result = AgentPluginParser().parse_zip(zip_bytes)
        assert result.meta is None
        assert any(d.code == "unsupported_schema" for d in result.diagnostics)

    def test_bad_mcp_disables_mcp_keeps_skills(self) -> None:
        zip_bytes = build_plugin_zip(
            {
                "plugin.json": default_plugin_json(),
                "skills/s/SKILL.md": "---\n---\nS.",
                "mcp.json": '{"$schema": "' + MCP_SCHEMA + '", "mcpServers": "broken"}',
            }
        )
        result = AgentPluginParser().parse_zip(zip_bytes)
        assert len(result.skills) == 1
        assert result.servers == []
        assert any(d.code == "mcp_invalid_servers" for d in result.diagnostics)

    def test_bad_server_variant_skipped_others_kept(self) -> None:
        zip_bytes = build_plugin_zip(
            {
                "plugin.json": default_plugin_json(),
                "mcp.json": json.dumps(
                    {
                        "$schema": MCP_SCHEMA,
                        "mcpServers": {
                            "good": {"type": "stdio", "command": "node"},
                            "bad": {"type": "stdio", "command": "../../escape"},
                            "weird": {"type": "nope"},
                        },
                    }
                ),
            }
        )
        result = AgentPluginParser().parse_zip(zip_bytes)
        assert [s.name for s in result.servers] == ["good"]
        mcp_diagnostics = [
            d for d in result.diagnostics if d.component.startswith("mcp:")
        ]
        assert len(mcp_diagnostics) == 2
        assert all(d.level == PluginDiagnosticLevel.WARNING for d in mcp_diagnostics)

    def test_mcp_version_mismatch_disables_mcp(self) -> None:
        # mcp.json uses the 1.0.0 MCP schema while plugin.json targets another
        # Agent Plugins version → MCP disabled (spec §10.1).
        from myrm_agent_harness.agent.plugins.mcp_config import validate_mcp_top_level

        raw = json.loads(
            json.dumps(
                {
                    "$schema": MCP_SCHEMA,
                    "mcpServers": {"x": {"type": "stdio", "command": "node"}},
                }
            )
        )
        other_plugin_schema = (
            "https://agent-plugins.org/schemas/0.9.0/plugin.schema.json"
        )
        with pytest.raises(McpConfigError) as exc:
            validate_mcp_top_level(raw, plugin_schema=other_plugin_schema)
        assert exc.value.code == "mcp_version_mismatch"

    def test_missing_mcp_json_is_fine(self) -> None:
        zip_bytes = build_plugin_zip({"plugin.json": default_plugin_json()})
        result = AgentPluginParser().parse_zip(zip_bytes)
        assert result.meta is not None
        assert result.servers == []

    def test_missing_skills_dir_is_fine(self) -> None:
        zip_bytes = build_plugin_zip({"plugin.json": default_plugin_json()})
        result = AgentPluginParser().parse_zip(zip_bytes)
        assert result.skills == []
        assert result.meta is not None

    def test_zip_bomb_raises_archive_security(self) -> None:
        from myrm_agent_harness.backends.skills.scanning.archive_security import (
            ArchiveSecurityError,
        )

        # > MAX_ZIP_ENTRY_COUNT (4096) members triggers ArchiveSecurityError
        # before any extraction happens.
        big: dict[str, str] = {"plugin.json": default_plugin_json()}
        for i in range(4200):
            big[f"skills/skill{i:04d}/SKILL.md"] = "---\n---\nX."
        zip_bytes = build_plugin_zip(big)
        with pytest.raises(ArchiveSecurityError):
            AgentPluginParser().parse_zip(zip_bytes)

    def test_non_zip_bytes_raises_bad_zip_file(self) -> None:
        """Garbage bytes surface as ``zipfile.BadZipFile`` (not swallowed).

        The framework lets the library exception propagate; the business layer
        wraps it into a user-facing 400. This test pins that contract so a future
        change cannot silently swallow corrupt uploads.
        """
        with pytest.raises(zipfile.BadZipFile):
            AgentPluginParser().parse_zip(b"\x00\x01not a real zip")


class TestParseResultFiles:
    """``PluginParseResult.files`` retains non-skill files for bundled MCP servers."""

    def test_retains_non_skill_files(self) -> None:
        zip_bytes = build_plugin_zip(
            {
                "plugin.json": default_plugin_json(),
                "mcp.json": json.dumps(
                    {
                        "$schema": MCP_SCHEMA,
                        "mcpServers": {
                            "pdf": {"type": "stdio", "command": "./bin/pdf"}
                        },
                    }
                ),
                "bin/pdf": "#!/bin/sh\necho ok",
                "skills/s/SKILL.md": "---\n---\nS.",
                "skills/s/tools/t.py": "print('t')",
            }
        )
        result = AgentPluginParser().parse_zip(zip_bytes)
        assert result.files.keys() == {"plugin.json", "mcp.json", "bin/pdf"}
        assert result.files["bin/pdf"] == b"#!/bin/sh\necho ok"
        # Skill files never leak into the top-level files tree.
        assert "skills/s/SKILL.md" not in result.files
        assert "skills/s/tools/t.py" not in result.files
        # The same skill file remains on the PluginSkill.files (unchanged).
        assert "SKILL.md" in result.skills[0].files

    def test_files_empty_without_extra_entries(self) -> None:
        zip_bytes = build_plugin_zip({"plugin.json": default_plugin_json()})
        result = AgentPluginParser().parse_zip(zip_bytes)
        assert set(result.files) == {"plugin.json"}

    def test_files_empty_on_fatal_manifest_failure(self) -> None:
        zip_bytes = build_plugin_zip({"plugin.json": "not json"})
        result = AgentPluginParser().parse_zip(zip_bytes)
        assert result.meta is None
        assert result.files == {}


class TestAgentAndWorkspaceDiscovery:
    """Discovers agents/*.md profiles and workspace/ template files."""

    def test_discovers_workbuddy_agents_and_workspace_assets(self) -> None:
        zip_bytes = build_plugin_zip(
            {
                "plugin.json": json.dumps(
                    {
                        "$schema": PLUGIN_SCHEMA,
                        "name": "research-squad",
                        "version": "1.0.0",
                        "entry_agent": "lead-analyst",
                    }
                ),
                "agents/lead-analyst.md": """---
name: Lead Analyst
description: Research team coordinator
max_iterations: 15
subagents:
  - Data Extractor
skills:
  - web-search
tools:
  - python_interpreter
---
You coordinate deep market research.
""",
                "agents/data-extractor.md": """---
name: Data Extractor
description: Extracts raw metrics
is_subagent: true
---
Extract structured numbers from documents.
""",
                "workspace/templates/report_template.xlsx": "binary_content_placeholder",
                "workspace/README.md": "# Research Workspace Guide",
            }
        )
        result = AgentPluginParser().parse_zip(zip_bytes)
        assert len(result.agents) == 2
        lead = next(a for a in result.agents if a.name == "Lead Analyst")
        assert lead.is_entry_agent is True
        assert lead.is_subagent is False
        assert lead.max_iterations == 15
        assert lead.subagent_names == ("Data Extractor",)
        assert "You coordinate deep market research." in lead.system_prompt

        extractor = next(a for a in result.agents if a.name == "Data Extractor")
        assert extractor.is_subagent is True
        assert "Extract structured numbers" in extractor.system_prompt

        assert "templates/report_template.xlsx" in result.workspace_files
        assert "README.md" in result.workspace_files
        assert result.workspace_files["README.md"] == b"# Research Workspace Guide"

    def test_discovers_agent_dir_layout_and_template_files_fallback(self) -> None:
        """Covers agents/<name>/AGENT.md layout and template_files/ fallback directory."""
        zip_bytes = build_plugin_zip(
            {
                "plugin.json": json.dumps(
                    {
                        "$schema": PLUGIN_SCHEMA,
                        "name": "dir-agent",
                        "version": "1.0.0",
                    }
                ),
                "agents/writer/AGENT.md": """---
name: Tech Writer
---
Write docs.
""",
                "template_files/init.sql": "CREATE TABLE test();",
            }
        )
        result = AgentPluginParser().parse_zip(zip_bytes)
        assert len(result.agents) == 1
        agent = result.agents[0]
        assert agent.name == "Tech Writer"
        assert agent.is_entry_agent is True  # default first agent is entry
        assert "Write docs." in agent.system_prompt
        assert "init.sql" in result.workspace_files


class TestPluginPackagingIntegrityGuard:
    """Tests for Roadmap Item 16: PluginPackagingIntegrityGuard."""

    def test_missing_stdio_bundled_artifact_generates_diagnostic_and_flags_server(self) -> None:
        """A stdio server referencing an entry point not present in the package is flagged with missing_artifact."""
        zip_bytes = build_plugin_zip(
            {
                "plugin.json": default_plugin_json(),
                "mcp.json": json.dumps(
                    {
                        "$schema": MCP_SCHEMA,
                        "mcpServers": {
                            "broken-local": {
                                "type": "stdio",
                                "command": "./dist/index.js",
                            },
                            "placeholder-local": {
                                "type": "stdio",
                                "command": "node",
                                "args": ["${PLUGIN_ROOT}/out/run.js"],
                            },
                            "working-remote": {
                                "type": "streamable-http",
                                "url": "https://api.example.com/mcp",
                            },
                        },
                    }
                ),
            }
        )
        result = AgentPluginParser().parse_zip(zip_bytes)
        assert len(result.servers) == 3

        broken = next(s for s in result.servers if s.name == "broken-local")
        assert broken.missing_artifact == "dist/index.js"

        placeholder = next(s for s in result.servers if s.name == "placeholder-local")
        assert placeholder.missing_artifact == "out/run.js"

        remote = next(s for s in result.servers if s.name == "working-remote")
        assert remote.missing_artifact is None

        # Verify diagnostics are populated
        diag_codes = [d.code for d in result.diagnostics]
        assert "mcp_missing_build_artifact" in diag_codes
        diag = next(d for d in result.diagnostics if d.code == "mcp_missing_build_artifact" and "broken-local" in d.component)
        assert "dist/index.js" in diag.message
        assert diag.level == PluginDiagnosticLevel.WARNING

    def test_existing_stdio_bundled_artifact_has_no_missing_flag(self) -> None:
        """When the entry point exists inside the package, missing_artifact is None and no warning is added."""
        zip_bytes = build_plugin_zip(
            {
                "plugin.json": default_plugin_json(),
                "dist/index.js": "console.log('mcp ready');",
                "mcp.json": json.dumps(
                    {
                        "$schema": MCP_SCHEMA,
                        "mcpServers": {
                            "valid-local": {
                                "type": "stdio",
                                "command": "./dist/index.js",
                            },
                        },
                    }
                ),
            }
        )
        result = AgentPluginParser().parse_zip(zip_bytes)
        assert len(result.servers) == 1
        valid = result.servers[0]
        assert valid.missing_artifact is None
        assert not any(d.code == "mcp_missing_build_artifact" for d in result.diagnostics)

        assert result.workspace_files["init.sql"] == b"CREATE TABLE test();"

    def test_packaging_integrity_guard_detects_missing_entrypoint_artifacts(self) -> None:
        """Covers PluginPackagingIntegrityGuard isolating servers with missing build artifacts."""
        zip_bytes = build_plugin_zip(
            {
                "plugin.json": default_plugin_json(),
                "mcp.json": json.dumps(
                    {
                        "$schema": MCP_SCHEMA,
                        "mcpServers": {
                            "broken-node-server": {
                                "type": "stdio",
                                "command": "node",
                                "args": ["./dist/index.js"],
                            },
                            "broken-direct-script": {
                                "type": "stdio",
                                "command": "./bin/run.js",
                            },
                            "valid-bundled-server": {
                                "type": "stdio",
                                "command": "./server.py",
                            },
                            "remote-api": {
                                "type": "streamable-http",
                                "url": "https://api.example.com/mcp",
                            },
                        },
                    }
                ),
                # Only valid-bundled-server's file and TypeScript sources are present
                "server.py": "#!/usr/bin/env python\nprint('mcp running')",
                "src/index.ts": "export const server = {};",
                "package.json": '{"name": "test-pkg"}',
            }
        )
        result = AgentPluginParser().parse_zip(zip_bytes)

        # Broken servers with missing build artifacts are filtered out of runnable servers
        assert len(result.servers) == 2
        server_names = {s.name for s in result.servers}
        assert "valid-bundled-server" in server_names
        assert "remote-api" in server_names

        # Missing entrypoint diagnostics are recorded with guidance
        missing_diags = [d for d in result.diagnostics if d.code == "mcp_missing_artifact"]
        assert len(missing_diags) == 2

        node_diag = next(d for d in missing_diags if d.component == "mcp:broken-node-server")
        assert "dist/index.js" in node_diag.message
        assert "npm run build" in node_diag.message

        direct_diag = next(d for d in missing_diags if d.component == "mcp:broken-direct-script")
        assert "bin/run.js" in direct_diag.message
