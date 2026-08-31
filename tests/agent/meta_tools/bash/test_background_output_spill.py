"""Tests for background bash stdout spill filenames (BSDL P0)."""

from __future__ import annotations

from pathlib import Path

import pytest

from myrm_agent_harness.agent.meta_tools.bash._background.output_spill import BackgroundOutputSpillWriter


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
        "myrm_agent_harness.runtime.paths.execution_paths.ensure_context_dir_exists",
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


@pytest.mark.asyncio
async def test_registry_output_includes_spill_log_ref_on_dropped(
    spill_session: tuple[str, Path],
) -> None:
    from collections import deque
    from myrm_agent_harness.agent.meta_tools.bash._background.consume import BackgroundRegistryEntry
    from myrm_agent_harness.agent.meta_tools.bash._background.registry import get_background_registry
    from myrm_agent_harness.agent.meta_tools.bash._background.types import BackgroundProcessInfo

    session_id, _ = spill_session
    registry = get_background_registry()
    pid = 99991

    writer = BackgroundOutputSpillWriter(session_id=session_id, job_id="job-99991")
    for i in range(85):
        writer.append_line("stdout", f"line-{i}")

    # Build entry with 200 items in buffer to simulate a dropped ring eviction
    buf: deque[tuple[int, str]] = deque([(i + 50, f"line-{i+50}") for i in range(200)], maxlen=200)
    entry = BackgroundRegistryEntry(
        info=BackgroundProcessInfo(
            job_id="job-99991",
            pid=pid,
            command="long_run",
            session_id=session_id,
            status="running",
            exit_code=None,
            started_at=1.0,
            error_category=None,
        ),
        proc=None,  # type: ignore[arg-type]
        stdout_buffer=buf,
        stderr_buffer=deque(),
        cursor=250,
        spill_writer=writer,
    )

    with registry._lock:
        registry._entries[pid] = entry

    # Poll with since_cursor=0 -> oldest kept is cursor 50 > baseline 0 + 1 and ring full -> dropped is True
    out = registry.get_output(pid, since_cursor=0)
    assert out["dropped"] is True
    assert out.get("spill_log_ref") == writer.vault_log_ref

