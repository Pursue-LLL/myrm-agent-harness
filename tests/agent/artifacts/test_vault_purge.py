"""Tests for ArtifactVault purge and cleanup capabilities."""

import tempfile
from pathlib import Path

from myrm_agent_harness.agent.artifacts.vault import ArtifactVault, VAULT_PREFIX


def test_vault_purge_object() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        vault = ArtifactVault(tmpdir)
        uri = vault.put("hello world content", "sample.txt", "text/plain", "Sample file")
        assert uri.startswith(VAULT_PREFIX)

        # 验证读取与列表
        assert vault.get(uri) == b"hello world content"
        assert len(vault.list_objects()) == 1

        # 执行单个 purge
        ok = vault.purge_object(uri)
        assert ok is True
        assert len(vault.list_objects()) == 0

        # 重复 purge 返回 False
        assert vault.purge_object(uri) is False


def test_vault_purge_by_task_id() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        vault = ArtifactVault(tmpdir)
        task_id = "test_task_12345"
        uri1 = vault.put("subagent output 1", f"subagent_{task_id}.md", "text/markdown", "Task 1 output")
        uri2 = vault.put("other data", "unrelated.txt", "text/plain", "Other output")

        assert len(vault.list_objects()) == 2

        purged = vault.purge_by_task_id(task_id)
        assert purged == 1

        remaining = vault.list_objects()
        assert len(remaining) == 1
        assert remaining[0].filename == "unrelated.txt"


def test_vault_purge_all() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        vault = ArtifactVault(tmpdir)
        vault.put("a", "a.txt")
        vault.put("b", "b.txt")
        vault.put("c", "c.txt")

        assert len(vault.list_objects()) == 3
        count = vault.purge_all()
        assert count == 3
        assert len(vault.list_objects()) == 0
