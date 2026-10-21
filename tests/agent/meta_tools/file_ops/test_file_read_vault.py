"""Tests for vault:// URI reads via file_ops vault_read helper."""

from __future__ import annotations

from pathlib import Path

import pytest

from myrm_agent_harness.agent.artifacts.vault import ArtifactVault
from myrm_agent_harness.agent.meta_tools.file_ops.utils.file_utils import parse_path_with_range
from myrm_agent_harness.agent.meta_tools.file_ops.utils.vault_read import (
    is_vault_uri,
    read_vault_text_content,
)


@pytest.fixture
def workspace(tmp_path: Path) -> str:
    return str(tmp_path)


class TestVaultReadHelpers:
    def test_is_vault_uri(self) -> None:
        assert is_vault_uri("vault://abc-123")
        assert is_vault_uri("vault://abc-123:1-50")
        assert not is_vault_uri("file.py")
        assert not is_vault_uri("/tmp/file.py:1-50")

    def test_parse_path_with_range_vault(self) -> None:
        uri, view_range = parse_path_with_range("vault://550e8400-e29b-41d4-a716-446655440000:2-4")
        assert uri == "vault://550e8400-e29b-41d4-a716-446655440000"
        assert view_range is not None
        assert view_range.start == 2
        assert view_range.end == 4

    def test_read_vault_full_content(self, workspace: str) -> None:
        vault = ArtifactVault(workspace)
        pointer = vault.put("line1\nline2\nline3\n", filename="result.txt")
        content = read_vault_text_content(pointer, workspace)
        assert content == "line1\nline2\nline3\n"

    def test_read_vault_line_range(self, workspace: str) -> None:
        vault = ArtifactVault(workspace)
        pointer = vault.put("line1\nline2\nline3\nline4\n", filename="result.txt")
        _, view_range = parse_path_with_range(f"{pointer}:2-3")
        content = read_vault_text_content(pointer, workspace, view_range=view_range)
        assert content == "line2\nline3\n"

    def test_read_vault_preview_mode(self, workspace: str) -> None:
        vault = ArtifactVault(workspace)
        lines = "\n".join(f"line{i}" for i in range(1, 1205))
        pointer = vault.put(lines + "\n", filename="big.txt")
        content = read_vault_text_content(pointer, workspace, mode="preview")
        assert "preview mode" in content
        assert "line1" in content

    def test_read_vault_invalid_uri_raises(self, workspace: str) -> None:
        with pytest.raises(ValueError, match="Invalid vault URI"):
            read_vault_text_content("not-vault", workspace)

        with pytest.raises(FileNotFoundError, match="not found or expired"):
            read_vault_text_content("vault://00000000-0000-0000-0000-000000000000", workspace)
