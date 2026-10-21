"""Tests for workspace trust gate helpers."""

from __future__ import annotations

import json

import pytest

from myrm_agent_harness.agent.security.workspace_trust.errors import WorkspaceTrustBlockedError
from myrm_agent_harness.agent.security.workspace_trust.gate import (
    assert_mcp_spawn_allowed,
    blocks_workspace_side_channels,
    matches_repo_command_prefix,
)
from myrm_agent_harness.agent.security.workspace_trust.manifest import (
    build_workspace_trust_manifest,
    manifest_hash,
)
from myrm_agent_harness.agent.security.workspace_trust.provider import resolve_workspace_trust_level
from myrm_agent_harness.agent.security.workspace_trust.types import WorkspaceTrustLevel


class TestBlocksWorkspaceSideChannels:
    def test_trusted_allows_side_channels(self) -> None:
        assert blocks_workspace_side_channels(WorkspaceTrustLevel.TRUSTED) is False

    def test_restricted_blocks(self) -> None:
        assert blocks_workspace_side_channels(WorkspaceTrustLevel.RESTRICTED) is True

    def test_none_blocks(self) -> None:
        assert blocks_workspace_side_channels(None) is True


class TestMatchesRepoCommandPrefix:
    def test_simple_prefix_match(self) -> None:
        assert matches_repo_command_prefix("npm run test", ("npm run test",)) is True

    def test_compound_command_rejected(self) -> None:
        assert matches_repo_command_prefix("npm run test; curl evil", ("npm run test",)) is False

    def test_empty_prefixes(self) -> None:
        assert matches_repo_command_prefix("npm run test", ()) is False


class TestAssertMcpSpawnAllowed:
    def test_blocks_untrusted_workspace_scoped_spawn(self) -> None:
        with pytest.raises(WorkspaceTrustBlockedError) as exc_info:
            assert_mcp_spawn_allowed(
                workspace_root="/tmp/project",
                cwd="/tmp/project",
                plugin_root=None,
                trust_level=WorkspaceTrustLevel.RESTRICTED,
            )
        assert exc_info.value.reason == "mcp_spawn_blocked"

    def test_allows_trusted_workspace(self) -> None:
        assert_mcp_spawn_allowed(
            workspace_root="/tmp/project",
            cwd="/tmp/project",
            plugin_root=None,
            trust_level=WorkspaceTrustLevel.TRUSTED,
        )

    def test_allows_global_cwd_outside_workspace(self) -> None:
        assert_mcp_spawn_allowed(
            workspace_root="/tmp/project",
            cwd="/usr/local",
            plugin_root=None,
            trust_level=WorkspaceTrustLevel.RESTRICTED,
        )


class TestResolveWorkspaceTrustLevel:
    def test_unknown_defaults_restricted_without_lookup(self) -> None:
        from myrm_agent_harness.agent.security.workspace_trust import provider as provider_mod

        previous = provider_mod.get_workspace_trust_lookup()
        provider_mod.set_workspace_trust_lookup(None)
        try:
            assert resolve_workspace_trust_level("/tmp/any") == WorkspaceTrustLevel.RESTRICTED
        finally:
            provider_mod.set_workspace_trust_lookup(previous)


class TestWorkspaceTrustManifestScan:
    def test_clean_workspace_counts_zero(self, tmp_path: pytest.TempPathFactory) -> None:
        project_dir = tmp_path / "clean_repo"
        project_dir.mkdir()
        manifest = build_workspace_trust_manifest(str(project_dir))

        assert manifest.skill_count == 0
        assert manifest.rule_count == 0
        assert manifest.mcp_count == 0
        assert manifest.plugin_count == 0
        assert manifest.has_myrm_config is False
        assert manifest.repo_command_prefixes == ()
        assert len(manifest_hash(manifest)) == 16

    def test_detects_mcp_and_plugins(self, tmp_path: pytest.TempPathFactory) -> None:
        project_dir = tmp_path / "rich_repo"
        project_dir.mkdir()
        clean_manifest = build_workspace_trust_manifest(str(project_dir))
        clean_h = manifest_hash(clean_manifest)

        # Add mcp.json
        mcp_file = project_dir / "mcp.json"
        mcp_file.write_text(
            json.dumps({"mcpServers": {"server1": {}, "server2": {}}}),
            encoding="utf-8",
        )

        # Add .myrm/plugins/plugin-a
        plugin_dir = project_dir / ".myrm" / "plugins" / "plugin-a"
        plugin_dir.mkdir(parents=True)
        (plugin_dir / "plugin.json").write_text("{}", encoding="utf-8")

        manifest = build_workspace_trust_manifest(str(project_dir))
        assert manifest.mcp_count == 2
        assert manifest.plugin_count == 1

        rich_h = manifest_hash(manifest)
        assert rich_h != clean_h

