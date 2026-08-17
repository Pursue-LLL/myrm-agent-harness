"""Integration tests: atomic persistence across session-continuity artifacts.

These tests exercise the real filesystem (no mocks on the critical write path)
to prove the crash-consistency guarantees the atomic-write fixes promise:

- context snapshot offload writes through the atomic byte path and is readable back
- teammate mailbox JSONL trim keeps a fully parseable file after exceeding the cap
- usage ledger concurrent appends never interleave into a corrupt JSONL
- encryption key file is written atomically with restricted permissions
- skill instance/state files are written atomically and round-trip

Each test uses a real ``LocalExecutor`` bound to a temp workspace (or a real
``tmp_path``) so the write path is the production one.
"""

from __future__ import annotations

import gzip
import json
import stat
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from myrm_agent_harness.agent.coordination.mailbox import (
    TeammateMailbox,
    list_teammate_history,
)
from myrm_agent_harness.agent.coordination.types import TeammateMessage
from myrm_agent_harness.backends.skills.state_manager import SkillStateManager
from myrm_agent_harness.backends.skills.types import SkillMetadata
from myrm_agent_harness.toolkits.code_execution.config import ExecutionConfig
from myrm_agent_harness.toolkits.code_execution.executors.local.executor import LocalExecutor
from myrm_agent_harness.utils.encryption_key import resolve_local_encryption_key
from myrm_agent_harness.utils.token_economics.usage_ledger import UsageLedger, UsageRecord


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    return tmp_path / "workspace"


@pytest.fixture
def executor(workspace: Path) -> LocalExecutor:
    return LocalExecutor(ExecutionConfig(), workspace_path=str(workspace))


@pytest.mark.integration
@pytest.mark.asyncio
async def test_context_snapshot_roundtrip_via_real_executor(
    executor: LocalExecutor, workspace: Path
) -> None:
    """A real snapshot write must land on disk atomically and be readable back.

    The snapshot path is normally under the sandbox ``/persistent`` mount, which
    does not exist on the local host. We adapt only the *path source* to the local
    workspace (environment adaptation); the write path itself
    (``write_file_bytes_atomic`` → real atomic rename) is the production one.
    """
    from unittest.mock import patch

    from langchain_core.messages import HumanMessage

    from myrm_agent_harness.runtime.context.offload import create_context_snapshot_callback

    snapshot_abs = str(workspace / ".context" / "chat_integ" / "snapshots" / "snap.jsonl.gz")
    snapshot_rel = ".context/chat_integ/snapshots/snap.jsonl.gz"

    with (
        patch(
            "myrm_agent_harness.runtime.context.offload.get_snapshot_path",
            return_value=snapshot_abs,
        ),
        patch(
            "myrm_agent_harness.runtime.context.offload.get_workspace_relative_path",
            return_value=snapshot_rel,
        ),
        patch(
            "myrm_agent_harness.runtime.context.offload.ensure_context_dir_exists",
            return_value=str(workspace / ".context" / "chat_integ" / "snapshots"),
        ),
    ):
        callback = create_context_snapshot_callback(executor)
        rel_path = await callback(
            messages=[HumanMessage(content="hello world")],
            chat_id="chat_integ",
            user_id="user",
        )
    assert rel_path == snapshot_rel

    # The snapshot must be readable back through the real executor.
    raw = await executor.read_file_bytes(rel_path)
    decompressed = gzip.decompress(raw).decode("utf-8")
    lines = decompressed.splitlines()
    assert len(lines) == 2  # header + one message
    header = json.loads(lines[0])
    assert header["_meta"] is True
    assert header["message_count"] == 1
    assert header["chat_id"] == "chat_integ"

    # No atomic temp residue left in the snapshot directory.
    snapshot_dir = workspace / ".context" / "chat_integ" / "snapshots"
    residue = [p for p in snapshot_dir.iterdir() if p.name.startswith(".atomic_")]
    assert residue == []


@pytest.mark.integration
def test_mailbox_trim_keeps_parseable_jsonl(tmp_path: Path) -> None:
    """After trimming past the cap, the JSONL must remain fully parseable."""
    from myrm_agent_harness.agent.coordination.mailbox import _MAX_JSONL_LINES

    workspace = tmp_path / "ws"
    workspace.mkdir()
    mailbox = TeammateMailbox("sess-trim-integ", workspace_path=str(workspace))
    msg = TeammateMessage(
        message_id="m-integ",
        session_id="sess-trim-integ",
        from_task_id="a",
        to_task_id="b",
        from_agent_type="coder",
        body="line",
        created_at=1.0,
    )
    path = workspace / "teammate_mailbox_sess-trim-integ.jsonl"
    path.write_text("\n".join('{"message_id":"x"}' for _ in range(_MAX_JSONL_LINES + 50)) + "\n")

    mailbox._persist(msg)

    # Every line must parse as JSON (no partial line from a non-atomic rewrite).
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) <= _MAX_JSONL_LINES
    for line in lines:
        json.loads(line)

    # The history reader must return the trimmed rows (pass a large limit).
    history = list_teammate_history("sess-trim-integ", str(workspace), limit=2000)
    assert len(history) == len(lines)


@pytest.mark.integration
def test_usage_ledger_concurrent_appends_stay_parseable(tmp_path: Path) -> None:
    """Concurrent appends must never interleave into a corrupt JSONL."""
    import threading

    ledger_dir = tmp_path / "session"
    ledger = UsageLedger(session_dir=ledger_dir)
    n_threads = 8
    n_per_thread = 40
    barrier = threading.Barrier(n_threads)

    def worker(_: int) -> None:
        barrier.wait()
        for i in range(n_per_thread):
            ledger.append(UsageRecord(model="m", total_tokens=i, cost_usd=0.001))

    with ThreadPoolExecutor(max_workers=n_threads) as pool:
        list(pool.map(worker, range(n_threads)))

    # Every line must parse; the ledger must recover all records.
    fp = ledger_dir / "usage_ledger.jsonl"
    lines = fp.read_text(encoding="utf-8").splitlines()
    assert len(lines) == n_threads * n_per_thread
    for line in lines:
        json.loads(line)
    records = ledger.load()
    assert len(records) == n_threads * n_per_thread


@pytest.mark.integration
def test_encryption_key_atomic_write_no_residue_and_permissions(tmp_path: Path) -> None:
    """The key file must be written atomically with 0600 and no temp residue."""
    state_dir = tmp_path / "state"
    key = resolve_local_encryption_key(str(state_dir))
    assert len(key) == 32

    key_file = state_dir / ".encryption_key"
    assert key_file.is_file()
    mode = key_file.stat().st_mode
    assert mode & stat.S_IRUSR
    assert mode & stat.S_IWUSR
    assert not (mode & stat.S_IRGRP)
    assert not (mode & stat.S_IROTH)

    residue = [p for p in state_dir.iterdir() if p.name.startswith(".atomic_")]
    assert residue == []

    # Re-resolving must return the same stable key (no re-keying).
    assert resolve_local_encryption_key(str(state_dir)) == key


@pytest.mark.integration
def test_skill_state_manager_atomic_roundtrip(tmp_path: Path) -> None:
    """Skill instance and state files must round-trip through the real filesystem."""
    manager = SkillStateManager(base_dir=str(tmp_path / "skills"))
    skill = SkillMetadata(name="github", description="test")

    config = manager.create_instance(
        skill_name="github",
        instance_name="personal",
        env_overrides={"TOKEN": "xxx"},
        config_overrides={"timeout": 30},
    )
    assert config.instance_name == "personal"

    manager.save_skill_state(skill, "personal", {"last_repo": "foo/bar", "count": 3})

    # Read back through a fresh manager (real disk round-trip).
    fresh = SkillStateManager(base_dir=str(tmp_path / "skills"))
    loaded_config = fresh.load_instance_config("github", "personal")
    assert loaded_config is not None
    assert loaded_config.env_overrides == {"TOKEN": "xxx"}
    assert loaded_config.config_overrides == {"timeout": 30}

    loaded_state = fresh.load_skill_state(skill, "personal")
    assert loaded_state == {"last_repo": "foo/bar", "count": 3}

    # No atomic temp residue anywhere under the skills tree.
    residue = [p for p in (tmp_path / "skills").rglob(".atomic_*")]
    assert residue == []


@pytest.mark.integration
def test_mailbox_send_persists_and_reads_back(tmp_path: Path) -> None:
    """A normal send must persist to JSONL and be readable back via history."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    mailbox = TeammateMailbox("sess-send-integ", workspace_path=str(workspace))
    msg = TeammateMessage(
        message_id="m-send-integ",
        session_id="sess-send-integ",
        from_task_id="a",
        to_task_id="b",
        from_agent_type="coder",
        body="hello teammate",
        created_at=1.0,
    )

    result = mailbox.send_sync(msg)
    assert result.accepted

    # The message must be readable back from the JSONL file.
    history = list_teammate_history("sess-send-integ", str(workspace))
    assert len(history) == 1
    assert history[0]["message_id"] == "m-send-integ"
    assert history[0]["body"] == "hello teammate"
    assert history[0]["from_task_id"] == "a"
    assert history[0]["to_task_id"] == "b"
