"""Unit tests for automatic staging and LRU preservation of unwritten deliverables."""

from __future__ import annotations

import tempfile
import time
from pathlib import Path

import pytest

from myrm_agent_harness.agent.middlewares.completion.deliverable_auto_staging import (
    MAX_STAGED_ARTIFACTS_LIMIT,
    STAGED_ARTIFACTS_DIR,
    _prune_old_staged_artifacts,
    stage_unwritten_deliverables,
)
from myrm_agent_harness.agent.middlewares.completion.deliverable_write_verifier import (
    UnwrittenDeliverable,
)


def test_stage_empty_deliverables_returns_empty() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        res = stage_unwritten_deliverables(tmp_dir, [])
        assert res == []


def test_stage_unwritten_deliverables_writes_files_and_meta() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        item = UnwrittenDeliverable(
            language="python",
            content="print('staged hello world')",
            line_count=1,
            filename_hint="tasks/demo.py",
            suggested_ext=".py",
            is_code=True,
        )

        res = stage_unwritten_deliverables(root, [item])
        assert len(res) == 1
        meta = res[0]
        assert meta.language == "python"
        assert meta.original_hint == "tasks/demo.py"
        assert meta.filename.endswith("_demo.py")

        staged_file = root / STAGED_ARTIFACTS_DIR / meta.filename
        assert staged_file.exists()
        assert staged_file.read_text(encoding="utf-8") == "print('staged hello world')"


def test_prune_old_staged_artifacts_enforces_limit() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        staged_dir = Path(tmp_dir) / STAGED_ARTIFACTS_DIR
        staged_dir.mkdir(parents=True, exist_ok=True)

        # Create 5 files with sequential timestamps
        created_files: list[Path] = []
        for i in range(5):
            f = staged_dir / f"draft_{i}.py"
            f.write_text(f"# file {i}", encoding="utf-8")
            created_files.append(f)
            time.sleep(0.01)

        # Prune to max 3 files
        _prune_old_staged_artifacts(staged_dir, max_keep=3)

        remaining = list(staged_dir.iterdir())
        assert len(remaining) == 3

        # Oldest two files should be pruned
        assert not created_files[0].exists()
        assert not created_files[1].exists()
        assert created_files[2].exists()
        assert created_files[3].exists()
        assert created_files[4].exists()


def test_staged_artifact_meta_to_dict_and_anonymous_deliverable() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        item = UnwrittenDeliverable(
            language="html",
            content="<h1>Test</h1>",
            line_count=1,
            filename_hint=None,
            suggested_ext=".html",
            is_code=False,
        )

        res = stage_unwritten_deliverables(root, [item])
        assert len(res) == 1
        meta = res[0]
        meta_dict = meta.to_dict()
        assert meta_dict["language"] == "html"
        assert meta_dict["filename"].endswith("draft_html_1.html")
        assert meta_dict["original_hint"] is None
        assert "artifact_id" in meta_dict


def test_prune_old_staged_artifacts_handles_nonexistent_and_errors() -> None:
    non_existent = Path("/non/existent/path/for/staging/pruning")
    # Must not raise
    _prune_old_staged_artifacts(non_existent)


def test_stage_unwritten_deliverables_handles_os_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    from pathlib import Path

    item = UnwrittenDeliverable(
        language="python",
        content="code",
        line_count=1,
        filename_hint="test.py",
        suggested_ext=".py",
        is_code=True,
    )

    def mock_mkdir(*args: object, **kwargs: object) -> None:
        raise OSError("Permission denied")

    monkeypatch.setattr(Path, "mkdir", mock_mkdir)
    res = stage_unwritten_deliverables("/tmp", [item])
    assert res == []


def test_stage_unwritten_deliverables_handles_write_bytes_error(monkeypatch: pytest.MonkeyPatch) -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        item = UnwrittenDeliverable(
            language="python",
            content="code",
            line_count=1,
            filename_hint="test.py",
            suggested_ext=".py",
            is_code=True,
        )

        def mock_write_bytes(*args: object, **kwargs: object) -> None:
            raise OSError("Disk full")

        monkeypatch.setattr(Path, "write_bytes", mock_write_bytes)
        res = stage_unwritten_deliverables(tmp_dir, [item])
        assert res == []


