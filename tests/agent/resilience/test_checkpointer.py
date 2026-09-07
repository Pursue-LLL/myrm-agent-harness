"""Tests for MarathonCheckpointer durable crash recovery."""

import tempfile
from pathlib import Path
import pytest

from myrm_agent_harness.agent.resilience.checkpointer import (
    MarathonCheckpointer,
    MarathonCheckpointRecord,
)


def test_marathon_checkpointer_save_and_load():
    with tempfile.TemporaryDirectory() as tmpdir:
        checkpointer = MarathonCheckpointer(storage_dir=tmpdir)
        session_id = "sess-test-123"

        record1 = checkpointer.save_checkpoint(
            session_id=session_id,
            step_index=1,
            step_name="scan_dependencies",
            completed_steps=["init"],
            pending_steps=["refactor", "test"],
            state_payload={"files_found": 5},
        )
        assert record1.step_index == 1
        assert record1.session_id == session_id

        record2 = checkpointer.save_checkpoint(
            session_id=session_id,
            step_index=2,
            step_name="refactor_code",
            completed_steps=["init", "scan_dependencies"],
            pending_steps=["test"],
            state_payload={"modified": ["app.py"]},
        )
        assert record2.step_index == 2

        latest = checkpointer.load_latest_checkpoint(session_id)
        assert latest is not None
        assert latest.step_index == 2
        assert latest.step_name == "refactor_code"
        assert latest.state_payload["modified"] == ["app.py"]

        all_records = checkpointer.list_checkpoints(session_id)
        assert len(all_records) == 2
        assert all_records[0].step_index == 1
        assert all_records[1].step_index == 2

        checkpointer.purge_session(session_id)
        assert checkpointer.load_latest_checkpoint(session_id) is None
