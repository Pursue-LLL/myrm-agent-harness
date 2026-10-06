"""Plugin bundle writer: strict inverse of the parser (round trip, determinism, strictness)."""

from __future__ import annotations

import io
import json
import zipfile

import pytest

from myrm_agent_harness.agent.plugins import (
    MYRM_NAMESPACE,
    AgentPluginParser,
    PluginAgent,
    PluginBundleSpec,
    PluginDiagnosticLevel,
    PluginMcpServer,
    build_plugin_bundle,
    is_excluded_path,
    is_valid_plugin_name,
    plugin_identity,
)
from myrm_agent_harness.agent.plugins.writer import render_bundle_files

SKILL_MD = b"---\nname: report-writer\ndescription: Writes reports\n---\nWrite the report.\n"


def _stdio(name: str = "sqlite", command: str = "uvx") -> PluginMcpServer:
    return PluginMcpServer(
        name=name,
        server_type="stdio",
        command=command,
        args=["mcp-server-sqlite"],
        url=None,
        headers=None,
        cwd=None,
        env_key_names=["API_KEY"],
        raw_env={"API_KEY": ""},
    )


def _remote() -> PluginMcpServer:
    return PluginMcpServer(
        name="remote",
        server_type="streamable_http",
        command=None,
        args=None,
        url="https://example.com/mcp",
        headers={"Authorization": "{{secret:Authorization}}"},
        cwd=None,
    )


def _team_spec() -> PluginBundleSpec:
    leader = PluginAgent(
        name="日报专家",
        description="Leads the team\n---\nsecond: line",
        system_prompt="  # Prompt\n\nDo things.\n---\nmore  ",
        max_iterations=12,
        skill_names=("report-writer",),
        mcp_names=("sqlite",),
        subagent_names=("Helper",),
        is_entry_agent=True,
        metadata={"model_selection": {"provider": "acme"}, "note": "a: b"},
    )
    helper = PluginAgent(name="Helper", description="Helps", system_prompt="Assist.", is_subagent=True)
    return PluginBundleSpec(
        name=plugin_identity("日报专家"),
        version="1.2.0",
        description="Team pack",
        keywords=("report", "team"),
        skills={"report-writer": {"SKILL.md": SKILL_MD, "scripts/run.py": b"print(1)\n"}},
        mcp_servers=(_stdio(), _remote()),
        agents=(leader, helper),
        workspace_files={"README.md": b"hello", "data/seed.csv": b"a,b\n1,2\n"},
        extensions={"ai.myrm.skill": {"originalName": "report-writer"}},
    )


class TestRules:
    @pytest.mark.parametrize("name", ["a", "daily-report", "a.b-c", "x" * 64])
    def test_valid_names(self, name: str) -> None:
        assert is_valid_plugin_name(name)

    @pytest.mark.parametrize("name", ["", "-a", "a-", "a--b", "a..b", "A", "a_b", "日报", "x" * 65])
    def test_invalid_names(self, name: str) -> None:
        assert not is_valid_plugin_name(name)

    def test_identity_is_plain_slug_when_lossless(self) -> None:
        assert plugin_identity("Daily Report") == "daily-report"
        assert plugin_identity("My_Skill") == "my-skill"

    def test_identity_never_collapses_distinct_display_names(self) -> None:
        first, second, third = plugin_identity("日报专家"), plugin_identity("周报专家"), plugin_identity("SEO 专家")
        assert len({first, second, third}) == 3
        assert all(is_valid_plugin_name(i) for i in (first, second, third, plugin_identity("")))
        assert third.startswith("seo-")

    def test_identity_stays_valid_for_very_long_names(self) -> None:
        assert is_valid_plugin_name(plugin_identity("专" * 500 + "x" * 500))

    @pytest.mark.parametrize("path", [".env", ".git/config", "a/.hidden/x", "__pycache__/x.pyc", "node_modules/p/i.js"])
    def test_excluded_paths(self, path: str) -> None:
        assert is_excluded_path(path)

    @pytest.mark.parametrize("path", ["SKILL.md", "scripts/run.py", "ai.myrm/agents/a.md"])
    def test_regular_paths_are_kept(self, path: str) -> None:
        assert not is_excluded_path(path)


class TestRoundTrip:
    def test_team_package_round_trips_through_parser(self) -> None:
        result = build_plugin_bundle(_team_spec())
        assert result.success, result.error
        assert result.filename == f"{plugin_identity('日报专家')}_v1.2.0.zip"

        parsed = AgentPluginParser().parse_zip(result.zip_content or b"")
        assert parsed.meta is not None and parsed.meta.version == "1.2.0"
        assert (
            parsed.meta.extensions[MYRM_NAMESPACE]["entryAgent"]
            == "agent-" + plugin_identity("日报专家").rsplit("-", 1)[1]
        )
        assert [s.name for s in parsed.skills] == ["report-writer"]
        assert parsed.skills[0].files["scripts/run.py"] == b"print(1)\n"
        assert {s.name for s in parsed.servers} == {"sqlite", "remote"}
        assert parsed.workspace_files == {"README.md": b"hello", "data/seed.csv": b"a,b\n1,2\n"}
        assert parsed.diagnostics == []

        by_name = {a.name: a for a in parsed.agents}
        leader, helper = by_name["日报专家"], by_name["Helper"]
        assert leader.is_entry_agent and not helper.is_entry_agent
        assert helper.is_subagent
        assert leader.subagent_names == ("Helper",)
        assert leader.system_prompt == "# Prompt\n\nDo things.\n---\nmore"
        assert leader.description == "Leads the team\n---\nsecond: line"
        assert leader.metadata["model_selection"] == {"provider": "acme"}

    def test_client_data_lives_only_under_the_namespace(self) -> None:
        files = render_bundle_files(_team_spec())
        assert set(files) == {
            "plugin.json",
            "mcp.json",
            "skills/report-writer/SKILL.md",
            "skills/report-writer/scripts/run.py",
            "ai.myrm/agents/agent-" + plugin_identity("日报专家").rsplit("-", 1)[1] + ".md",
            "ai.myrm/agents/helper.md",
            "ai.myrm/workspace/README.md",
            "ai.myrm/workspace/data/seed.csv",
        }
        manifest = json.loads(files["plugin.json"])
        assert set(manifest) <= {"$schema", "name", "version", "description", "author", "keywords", "extensions"}

    def test_output_is_deterministic(self) -> None:
        first = build_plugin_bundle(_team_spec())
        second = build_plugin_bundle(_team_spec())
        assert first.zip_content == second.zip_content

    def test_secrets_never_leave_through_env_or_headers(self) -> None:
        mcp = json.loads(render_bundle_files(_team_spec())["mcp.json"])
        assert mcp["mcpServers"]["sqlite"]["env"] == {"API_KEY": ""}
        assert mcp["mcpServers"]["remote"]["headers"] == {"Authorization": "{{secret:Authorization}}"}
        assert mcp["mcpServers"]["remote"]["type"] == "streamable-http"

    def test_first_non_subagent_becomes_entry_when_none_flagged(self) -> None:
        spec = PluginBundleSpec(
            name="pair",
            agents=(
                PluginAgent(name="Sub", is_subagent=True),
                PluginAgent(name="Lead"),
            ),
        )
        parsed = AgentPluginParser().parse_zip(build_plugin_bundle(spec).zip_content or b"")
        assert [a.name for a in parsed.agents if a.is_entry_agent] == ["Lead"]

    def test_same_display_names_get_distinct_slugs(self) -> None:
        spec = PluginBundleSpec(name="twins", agents=(PluginAgent(name="Twin"), PluginAgent(name="Twin")))
        assert set(render_bundle_files(spec)) >= {"ai.myrm/agents/twin.md", "ai.myrm/agents/twin-2.md"}


class TestStrictness:
    @pytest.mark.parametrize(
        ("spec", "message"),
        [
            (PluginBundleSpec(name="Bad Name"), "Invalid plugin name"),
            (PluginBundleSpec(name="ok", skills={"s": {"notes.md": b"x"}}), "no SKILL.md"),
            (PluginBundleSpec(name="ok", skills={"s": {"SKILL.md": SKILL_MD, ".env": b"K=1"}}), "Excluded file path"),
            (PluginBundleSpec(name="ok", skills={"s": {"SKILL.md": SKILL_MD, "../x": b"1"}}), "Unsafe file path"),
            (PluginBundleSpec(name="ok", skills={"a/b": {"SKILL.md": SKILL_MD}}), "Invalid skill directory name"),
            (PluginBundleSpec(name="ok", workspace_files={"big.bin": b"0" * (1024 * 1024 + 1)}), "exceeds"),
            (PluginBundleSpec(name="ok", mcp_servers=(_stdio(), _stdio())), "Duplicate MCP server"),
        ],
    )
    def test_rejects_instead_of_silently_dropping(self, spec: PluginBundleSpec, message: str) -> None:
        result = build_plugin_bundle(spec)
        assert not result.success
        assert message in (result.error or "")

    def test_non_portable_mcp_server_fails_the_self_check(self) -> None:
        result = build_plugin_bundle(PluginBundleSpec(name="ok", mcp_servers=(_stdio(command="/usr/local/bin/srv"),)))
        assert not result.success
        assert "self-check failed" in (result.error or "")

    def test_non_serializable_agent_metadata_is_rejected(self) -> None:
        agent = PluginAgent(name="Odd", metadata={"x": object()})
        result = build_plugin_bundle(PluginBundleSpec(name="ok", agents=(agent,)))
        assert not result.success
        assert "non-serializable" in (result.error or "")


def _zip(entries: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for path, content in entries.items():
            archive.writestr(f"plugin/{path}", content)
    return buffer.getvalue()


_MANIFEST = json.dumps(
    {"$schema": "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json", "name": "plugin", "version": "1.0.0"}
).encode()


class TestNamespaceInbound:
    def test_namespaced_agents_win_over_community_layout(self) -> None:
        archive = _zip(
            {
                "plugin.json": _MANIFEST,
                "ai.myrm/agents/main.md": b"---\nname: Main\n---\nnamespaced",
                "agents/legacy.md": b"---\nname: Legacy\n---\ncommunity",
                "ai.myrm/workspace/a.txt": b"ns",
                "workspace/b.txt": b"legacy",
            }
        )
        parsed = AgentPluginParser().parse_zip(archive)
        assert [a.name for a in parsed.agents] == ["Main"]
        assert parsed.workspace_files == {"a.txt": b"ns"}

    def test_community_layout_is_still_accepted_inbound(self) -> None:
        archive = _zip(
            {
                "plugin.json": _MANIFEST,
                "agents/a.md": b"---\nname: A\n---\nfirst",
                "agents/b.md": b"---\nname: B\n---\nsecond",
                "template_files/init.sql": b"select 1;",
            }
        )
        parsed = AgentPluginParser().parse_zip(archive)
        assert [a.is_entry_agent for a in parsed.agents] == [True, False]
        assert parsed.workspace_files == {"init.sql": b"select 1;"}

    def test_entry_agent_hint_from_namespace_extension(self) -> None:
        manifest = json.dumps(
            {
                "$schema": "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json",
                "name": "plugin",
                "extensions": {MYRM_NAMESPACE: {"entryAgent": "second"}},
            }
        ).encode()
        archive = _zip(
            {
                "plugin.json": manifest,
                "ai.myrm/agents/first.md": b"---\nname: First\n---\nx",
                "ai.myrm/agents/second.md": b"---\nname: Second\n---\ny",
            }
        )
        parsed = AgentPluginParser().parse_zip(archive)
        assert [a.name for a in parsed.agents if a.is_entry_agent] == ["Second"]

    def test_hidden_files_are_reported_but_platform_noise_is_not(self) -> None:
        noisy = _zip({"plugin.json": _MANIFEST, ".DS_Store": b"x", "__MACOSX/a": b"x", "node_modules/p/i.js": b"x"})
        assert AgentPluginParser().parse_zip(noisy).diagnostics == []

        hidden = _zip({"plugin.json": _MANIFEST, ".env.example": b"K=", "ai.myrm/agents/.draft.md": b"x"})
        diagnostics = AgentPluginParser().parse_zip(hidden).diagnostics
        assert [(d.code, d.level) for d in diagnostics] == [("files_ignored", PluginDiagnosticLevel.INFO)]
        assert ".env.example" in diagnostics[0].message
