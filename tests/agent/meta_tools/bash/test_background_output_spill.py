"""Tests for background bash stdout spill filenames (BSDL P0)."""

from __future__ import annotations

from pathlib import Path

import pytest

from myrm_agent_harness.agent.meta_tools.bash._background_output_spill import BackgroundOutputSpillWriter


@pytest.fixture
def spill_session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[str, Path]:
    session_id = "session-spill-test"
    evicted_dir = tmp_path / ".context" / session_id / "evicted"
    evicted_dir.mkdir(parents=True)

    def _ensure_context_dir_exists(sid: str, subdir: str) -> str:
        assert sid == session_id
        assert subdir == "evicted"
        return str(evicted_dir)

    monkeypatch.setattr(
        "myrm_agent_harness.runtime.execution_paths.ensure_context_dir_exists",
        _ensure_context_dir_exists,
    )
    return session_id, evicted_dir


def test_spill_uses_evicted_api_filename(spill_session: tuple[str, Path]) -> None:
    session_id, evicted_dir = spill_session
    writer = BackgroundOutputSpillWriter(session_id=session_id, job_id="job-1")

    for i in range(80):
        writer.append_line("stdout", f"line-{i}")

    ref = writer.vault_log_ref
    assert ref is not None
    assert ref.startswith("output_")
    assert ref.endswith(".txt")
    assert (evicted_dir / ref).is_file()
