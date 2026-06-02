"""Tests for myrm_agent_harness.runtime.artifact_judge.ArtifactJudge."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from myrm_agent_harness.runtime.artifact_judge import ArtifactJudge


@pytest.fixture
def judge() -> ArtifactJudge:
    return ArtifactJudge()


def test_should_persist_code_and_config_extensions(judge: ArtifactJudge, tmp_path: Path) -> None:
    root = str(tmp_path)
    assert judge.should_persist(str(tmp_path / "a.py"), root)[0] is True
    assert judge.should_persist(str(tmp_path / "b.js"), root)[0] is True
    assert judge.should_persist(str(tmp_path / "c.ts"), root)[0] is True
    assert judge.should_persist(str(tmp_path / "cfg.json"), root)[0] is True
    assert judge.should_persist(str(tmp_path / "d.yaml"), root)[0] is True


def test_should_persist_blacklist_overrides_extension(judge: ArtifactJudge, tmp_path: Path) -> None:
    root = str(tmp_path)
    p = tmp_path / "node_modules" / "pkg" / "x.py"
    p.parent.mkdir(parents=True)
    p.write_text("#")
    ok, reason = judge.should_persist(str(p), root)
    assert ok is False
    assert "node_modules" in reason

    q = tmp_path / "pkg" / "__pycache__" / "mod.cpython-313.pyc"
    q.parent.mkdir(parents=True)
    q.write_bytes(b"")
    ok2, reason2 = judge.should_persist(str(q), root)
    assert ok2 is False
    assert "__pycache__" in reason2


def test_should_persist_whitelist_directories(judge: ArtifactJudge, tmp_path: Path) -> None:
    root = str(tmp_path)
    for sub in ("src", "lib", "tests"):
        f = tmp_path / sub / "plain.bin"
        f.parent.mkdir(parents=True)
        f.write_bytes(b"\x00")
        assert judge.should_persist(str(f), root)[0] is True


def test_should_persist_no_rule(judge: ArtifactJudge, tmp_path: Path) -> None:
    root = str(tmp_path)
    f = tmp_path / "unknown.xyz"
    f.write_text("")
    ok, reason = judge.should_persist(str(f), root)
    assert ok is False
    assert reason == "No matching rule"


def test_should_persist_user_feedback_priority(judge: ArtifactJudge, tmp_path: Path) -> None:
    root = str(tmp_path)
    rel = "node_modules/forced.py"
    judge.record_feedback(rel, True)
    p = tmp_path / rel
    p.parent.mkdir(parents=True)
    p.write_text("#")
    ok, reason = judge.should_persist(str(p), root)
    assert ok is True
    assert reason == "User feedback"


@patch("myrm_agent_harness.runtime.execution_paths.is_context_path")
@patch("myrm_agent_harness.runtime.execution_paths.is_persistent_path")
def test_should_persist_persistent_context_paths(
    mock_persistent: MagicMock,
    mock_context: MagicMock,
    judge: ArtifactJudge,
    tmp_path: Path,
) -> None:
    root = str(tmp_path)
    mock_persistent.return_value = True
    mock_context.return_value = True
    f = tmp_path / "ctx.txt"
    f.write_text("")
    ok, reason = judge.should_persist(str(f), root)
    assert ok is True
    assert "Context file" in reason


@patch("myrm_agent_harness.runtime.execution_paths.is_context_path")
@patch("myrm_agent_harness.runtime.execution_paths.is_persistent_path")
def test_should_persist_persistent_not_context_falls_through(
    mock_persistent: MagicMock,
    mock_context: MagicMock,
    judge: ArtifactJudge,
    tmp_path: Path,
) -> None:
    root = str(tmp_path)
    mock_persistent.return_value = True
    mock_context.return_value = False
    f = tmp_path / "plain.bin"
    f.write_bytes(b"\x00")
    ok, _ = judge.should_persist(str(f), root)
    assert ok is False


def test_scan_workspace_classifies(tmp_path: Path) -> None:
    judge = ArtifactJudge()
    root = tmp_path
    (root / "src").mkdir()
    (root / "src" / "a.py").write_text("x")
    (root / "tmp.bin").write_bytes(b"\x00")
    out = judge.scan_workspace(str(root))
    persist = {Path(p).name for p in out["persist"]}
    ephemeral = {Path(p).name for p in out["ephemeral"]}
    assert "a.py" in persist
    assert "tmp.bin" in ephemeral


def test_record_feedback_and_statistics(judge: ArtifactJudge) -> None:
    judge.record_feedback("rel/path.py", False)
    stats = judge.get_statistics()
    assert stats["user_feedback_count"] == 1
    assert stats["artifact_extensions"] > 0
    assert stats["artifact_directories"] > 0
    assert stats["blacklist_patterns"] > 0
