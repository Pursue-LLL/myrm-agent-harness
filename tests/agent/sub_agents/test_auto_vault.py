"""Tests for subagent auto-vault result pipeline.

Verifies that oversized subagent outputs are automatically stored in ArtifactVault
and replaced with a summary + vault:// pointer, falling back to truncation when
vault is unavailable.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from myrm_agent_harness.agent.sub_agents.executor import (
    _auto_vault_or_truncate,
    _parse_handover_state,
)
from myrm_agent_harness.agent.sub_agents.types import SubagentConfig


@pytest.fixture
def workspace(tmp_path: Path) -> str:
    return str(tmp_path)


@pytest.fixture
def config_with_vault() -> SubagentConfig:
    return SubagentConfig(
        system_prompt="test",
        auto_vault_threshold=100,
        max_result_tokens=50,
    )


@pytest.fixture
def config_without_vault() -> SubagentConfig:
    return SubagentConfig(
        system_prompt="test",
        auto_vault_threshold=None,
        max_result_tokens=50,
    )


class TestAutoVaultOrTruncate:
    """Test _auto_vault_or_truncate function."""

    def test_short_result_not_vaulted(self, config_with_vault: SubagentConfig, workspace: str) -> None:
        """Results under threshold should pass through to truncation."""
        result = _auto_vault_or_truncate(
            "short output", config_with_vault,
            {"workspace_path": workspace}, "task-1", "test",
        )
        assert "vault://" not in result
        assert "short output" in result

    def test_long_result_auto_vaulted(self, config_with_vault: SubagentConfig, workspace: str) -> None:
        """Results exceeding threshold should be stored in vault."""
        long_output = "x" * 200
        result = _auto_vault_or_truncate(
            long_output, config_with_vault,
            {"workspace_path": workspace}, "task-1", "test",
        )
        assert "vault://" in result
        assert "[Full result stored in vault:" in result

    def test_long_result_pushes_inline_artifact(
        self, config_with_vault: SubagentConfig, workspace: str
    ) -> None:
        """Auto-vault should queue an inline artifact for frontend delivery."""
        from myrm_agent_harness.agent.artifacts import ArtifactContextManager, get_artifact_context

        long_output = "x" * 200
        with ArtifactContextManager(message_id="msg_auto_vault"):
            result = _auto_vault_or_truncate(
                long_output,
                config_with_vault,
                {"workspace_path": workspace},
                "task-1",
                "test",
            )
            assert "vault://" in result
            ctx = get_artifact_context()
            assert ctx is not None
            events = ctx.inline_artifact_queue.pop_events()
            assert len(events) == 1
            assert events[0].filename == "subagent_task-1.md"
            assert events[0].preview_url.startswith("vault://")
            assert events[0].content_type == "text/markdown"

    def test_vault_pointer_is_valid_uuid(self, config_with_vault: SubagentConfig, workspace: str) -> None:
        """The vault pointer should contain a valid UUID."""
        import re
        long_output = "x" * 200
        result = _auto_vault_or_truncate(
            long_output, config_with_vault,
            {"workspace_path": workspace}, "task-1", "test",
        )
        match = re.search(r"vault://([a-f0-9-]+)", result)
        assert match is not None
        assert len(match.group(1)) == 36  # UUID format

    def test_vaulted_file_readable(self, config_with_vault: SubagentConfig, workspace: str) -> None:
        """The vault file should contain the original full result."""
        import re

        from myrm_agent_harness.agent.artifacts.vault import ArtifactVault

        long_output = "hello " * 100
        result = _auto_vault_or_truncate(
            long_output, config_with_vault,
            {"workspace_path": workspace}, "task-1", "test",
        )
        match = re.search(r"(vault://[a-f0-9-]+)", result)
        assert match
        assert 'file_read_tool(paths=["' in result
        vault = ArtifactVault(workspace)
        content = vault.get(match.group(1))
        assert content.decode("utf-8") == long_output

    def test_isolated_workspace_vaults_to_parent(
        self, config_with_vault: SubagentConfig, tmp_path: Path
    ) -> None:
        """ISOLATED_COPY: vault must land in parent workspace, not child temp dir."""
        import re

        from myrm_agent_harness.agent.artifacts.vault import ArtifactVault

        parent_ws = tmp_path / "parent"
        child_ws = tmp_path / "child"
        parent_ws.mkdir()
        child_ws.mkdir()

        long_output = "isolated " * 50
        result = _auto_vault_or_truncate(
            long_output,
            config_with_vault,
            {
                "workspace_path": str(child_ws),
                "_isolated_parent_workspace": str(parent_ws),
            },
            "task-iso",
            "test",
        )
        match = re.search(r"(vault://[a-f0-9-]+)", result)
        assert match is not None

        parent_vault = ArtifactVault(str(parent_ws))
        assert parent_vault.get(match.group(1)).decode("utf-8") == long_output

        child_objects = child_ws / ".agent" / "vault" / "objects"
        assert not child_objects.exists() or not any(child_objects.iterdir())

    def test_summary_contains_head_and_tail(self, config_with_vault: SubagentConfig, workspace: str) -> None:
        """Summary should contain the beginning and end of the result."""
        head = "HEAD_MARKER_" + "a" * 50
        tail = "b" * 50 + "_TAIL_MARKER"
        middle = "m" * 200
        long_output = head + middle + tail
        result = _auto_vault_or_truncate(
            long_output, config_with_vault,
            {"workspace_path": workspace}, "task-1", "test",
        )
        assert "HEAD_MARKER" in result
        assert "TAIL_MARKER" in result

    def test_disabled_vault_uses_truncation(self, config_without_vault: SubagentConfig, workspace: str) -> None:
        """When auto_vault_threshold is None, should always truncate."""
        long_output = "x" * 200
        result = _auto_vault_or_truncate(
            long_output, config_without_vault,
            {"workspace_path": workspace}, "task-1", "test",
        )
        assert "vault://" not in result

    def test_no_workspace_falls_back_to_truncation(self, config_with_vault: SubagentConfig) -> None:
        """Without workspace_path in context, should fall back to truncation."""
        long_output = "x" * 200
        result = _auto_vault_or_truncate(
            long_output, config_with_vault,
            {}, "task-1", "test",
        )
        assert "vault://" not in result

    def test_invalid_workspace_falls_back(self, config_with_vault: SubagentConfig) -> None:
        """Non-string workspace_path should fall back to truncation."""
        long_output = "x" * 200
        result = _auto_vault_or_truncate(
            long_output, config_with_vault,
            {"workspace_path": 12345}, "task-1", "test",
        )
        assert "vault://" not in result

    def test_default_threshold_is_8000(self) -> None:
        """Default auto_vault_threshold should be 8000."""
        config = SubagentConfig(system_prompt="test")
        assert config.auto_vault_threshold == 8000


class TestAutoVaultYAMLConfig:
    """Test auto_vault_threshold in YAML config loader."""

    def test_yaml_with_auto_vault_threshold(self, tmp_path: Path) -> None:
        """auto_vault_threshold should be parsed from YAML config section."""
        from myrm_agent_harness.agent.sub_agents.config_loader import SubagentConfigLoader

        yaml_content = """
name: test_vault
description: Test vault config
tools: []
system_prompt: |
  You are a test agent.
config:
  auto_vault_threshold: 5000
"""
        config_file = tmp_path / "test_vault.yaml"
        config_file.write_text(yaml_content)

        loader = SubagentConfigLoader()
        config = loader.load_from_yaml(config_file)

        assert config is not None
        assert config.auto_vault_threshold == 5000

    def test_yaml_disable_auto_vault(self, tmp_path: Path) -> None:
        """Setting auto_vault_threshold to null should disable it."""
        from myrm_agent_harness.agent.sub_agents.config_loader import SubagentConfigLoader

        yaml_content = """
name: test_no_vault
description: Test no vault
tools: []
system_prompt: |
  You are a test agent.
config:
  auto_vault_threshold: null
"""
        config_file = tmp_path / "test_no_vault.yaml"
        config_file.write_text(yaml_content)

        loader = SubagentConfigLoader()
        config = loader.load_from_yaml(config_file)

        assert config is not None
        assert config.auto_vault_threshold is None

    def test_yaml_default_auto_vault(self, tmp_path: Path) -> None:
        """When not specified in YAML, auto_vault_threshold should use default (8000)."""
        from myrm_agent_harness.agent.sub_agents.config_loader import SubagentConfigLoader

        yaml_content = """
name: test_default
description: Test default vault
tools: []
system_prompt: |
  You are a test agent.
config: {}
"""
        config_file = tmp_path / "test_default.yaml"
        config_file.write_text(yaml_content)

        loader = SubagentConfigLoader()
        config = loader.load_from_yaml(config_file)

        assert config is not None
        assert config.auto_vault_threshold == 8000


class TestParseHandoverState:
    """Test _parse_handover_state helper."""

    def test_no_handover_tag(self) -> None:
        assert _parse_handover_state("Just a normal result", "t1") is None

    def test_valid_handover_json(self) -> None:
        raw = 'prefix <handover>{"status": "completed", "summary": "Done"}</handover> suffix'
        state = _parse_handover_state(raw, "t1")
        assert state is not None

    def test_handover_with_markdown_fences(self) -> None:
        raw = '<handover>```json\n{"status": "ok"}\n```</handover>'
        state = _parse_handover_state(raw, "t1")
        assert state is not None

    def test_invalid_handover_json(self) -> None:
        raw = "<handover>not json</handover>"
        state = _parse_handover_state(raw, "t1")
        assert state is None
