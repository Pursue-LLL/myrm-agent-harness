"""Tests for ArtifactVault purge and cleanup capabilities."""

import tempfile

import pytest

from myrm_agent_harness.agent.artifacts.vault import VAULT_PREFIX, ArtifactVault, VaultObject


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
        vault.put("subagent output 1", f"subagent_{task_id}.md", "text/markdown", "Task 1 output")
        vault.put("other data", "unrelated.txt", "text/plain", "Other output")

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


def test_vault_purge_by_task_ids_scans_the_vault_once(monkeypatch: pytest.MonkeyPatch) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        vault = ArtifactVault(tmpdir)
        vault.put("a", "subagent_task_a.md", "text/markdown", "A output")
        vault.put("b", "other.md", "text/markdown", "subagent_task_b described here")
        vault.put("c", "subagent_task_c.md", "text/markdown", "C output")
        vault.put("d", "unrelated.txt", "text/plain", "Other output")

        scans = 0
        list_objects = vault.list_objects

        def counting_list_objects() -> list[VaultObject]:
            nonlocal scans
            scans += 1
            return list_objects()

        monkeypatch.setattr(vault, "list_objects", counting_list_objects)

        assert vault.purge_by_task_ids(["task_a", "task_b", "task_missing"]) == 2

        assert scans == 1
        assert sorted(obj.filename for obj in list_objects()) == ["subagent_task_c.md", "unrelated.txt"]


def test_vault_purge_by_task_ids_without_ids_does_not_touch_the_vault() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        vault = ArtifactVault(tmpdir)
        vault.put("a", "subagent_task_a.md", "text/markdown", "A output")

        assert vault.purge_by_task_ids([]) == 0
        assert vault.purge_by_task_ids([""]) == 0
        assert len(vault.list_objects()) == 1
