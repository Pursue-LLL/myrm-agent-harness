"""Unit tests for agent-facing ground truth drift defense tool and MemoryManager mixin.

[INPUT]
- toolkits.memory.drift_defense.tool::create_ground_truth_drift_check_tool, CheckMemoryDriftInput
- toolkits.memory.drift_defense.types::DriftCheckRequest, DriftCheckResult, DriftType
- toolkits.memory._manager.drift_defense::MemoryManagerDriftDefenseMixin
- toolkits.memory.manager::MemoryManager

[OUTPUT]
- test_drift_check_tool_pristine: verifies tool output for existing files and symbols
- test_drift_check_tool_missing_file: verifies tool detection for deleted/missing files
- test_drift_check_tool_missing_symbol: verifies tool detection for deleted symbols
- test_memory_manager_drift_defense_mixin: verifies MemoryManager mixin methods

[POS]
Integration and unit tests ensuring Agent runtime and MemoryManager can detect ground truth drift.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from myrm_agent_harness.toolkits.memory._manager.drift_defense import (
    MemoryManagerDriftDefenseMixin,
)
from myrm_agent_harness.toolkits.memory.drift_defense.tool import (
    create_ground_truth_drift_check_tool,
)
from myrm_agent_harness.toolkits.memory.drift_defense.types import (
    DriftCheckRequest,
    DriftType,
)
from myrm_agent_harness.toolkits.memory.manager import MemoryManager


class DummyDriftMemoryManager(MemoryManagerDriftDefenseMixin):
    """Dummy manager subclass for testing drift defense mixin."""

    def __init__(self) -> None:
        self.user_id = "test_user"


@pytest.fixture
def temp_workspace() -> Path:
    """Create a temporary workspace directory populated with test python files."""
    with tempfile.TemporaryDirectory() as td:
        ws = Path(td)
        src = ws / "services"
        src.mkdir(parents=True, exist_ok=True)
        py_file = src / "auth.py"
        py_file.write_text(
            "class AuthService:\n"
            "    def authenticate(self, token: str) -> bool:\n"
            "        return bool(token)\n",
            encoding="utf-8",
        )
        yield ws


def test_drift_check_tool_pristine(temp_workspace: Path) -> None:
    """Ensure agent tool confirms zero drift when referenced file and symbol exist."""
    tool = create_ground_truth_drift_check_tool()
    payload = {
        "memory_id": "mem-101",
        "content": "Verify authorization tokens using services/auth.py AuthService.",
        "workspace_root": str(temp_workspace),
        "recorded_path": "services/auth.py",
        "recorded_symbol": "AuthService",
    }
    raw_res = tool.invoke(payload)
    data = json.loads(raw_res)

    assert data["memory_id"] == "mem-101"
    assert data["is_drifted"] is False
    assert data["confidence_penalty"] == 0.0
    assert len(data["findings"]) == 0
    assert "[⚠️ 过时警告" not in data["decorated_content"]


def test_drift_check_tool_missing_file(temp_workspace: Path) -> None:
    """Ensure agent tool flags drift when bound file does not exist."""
    tool = create_ground_truth_drift_check_tool()
    payload = {
        "memory_id": "mem-102",
        "content": "Legacy auth logic located at services/legacy_auth.py.",
        "workspace_root": str(temp_workspace),
        "recorded_path": "services/legacy_auth.py",
    }
    raw_res = tool.invoke(payload)
    data = json.loads(raw_res)

    assert data["memory_id"] == "mem-102"
    assert data["is_drifted"] is True
    assert data["confidence_penalty"] > 0.0
    assert len(data["findings"]) >= 1
    assert any(f["drift_type"] == DriftType.FILE_NOT_FOUND.value for f in data["findings"])
    assert "[⚠️ 过时警告" in data["decorated_content"]


def test_drift_check_tool_missing_symbol(temp_workspace: Path) -> None:
    """Ensure agent tool flags drift when symbol is no longer in file."""
    tool = create_ground_truth_drift_check_tool()
    payload = {
        "memory_id": "mem-103",
        "content": "Old token decoder class services/auth.py LegacyTokenDecoder.",
        "workspace_root": str(temp_workspace),
        "recorded_path": "services/auth.py",
        "recorded_symbol": "LegacyTokenDecoder",
    }
    raw_res = tool.invoke(payload)
    data = json.loads(raw_res)

    assert data["memory_id"] == "mem-103"
    assert data["is_drifted"] is True
    assert len(data["findings"]) >= 1
    assert any(f["drift_type"] == DriftType.SYMBOL_NOT_FOUND.value for f in data["findings"])
    assert any("LegacyTokenDecoder" in f["reference_target"] for f in data["findings"])


def test_memory_manager_drift_defense_mixin(temp_workspace: Path) -> None:
    """Verify MemoryManager integrates drift defense check and decoration methods."""
    assert issubclass(MemoryManager, MemoryManagerDriftDefenseMixin)

    manager = DummyDriftMemoryManager()

    req1 = DriftCheckRequest(
        memory_id="m1",
        content="Use services/auth.py AuthService",
        workspace_root=temp_workspace,
        recorded_path="services/auth.py",
        recorded_symbol="AuthService",
    )
    req2 = DriftCheckRequest(
        memory_id="m2",
        content="Deleted helper services/ghost.py",
        workspace_root=temp_workspace,
        recorded_path="services/ghost.py",
    )

    res1 = manager.check_memory_ground_truth_drift(req1)
    assert res1.is_drifted is False

    batch_results = manager.batch_check_memory_drift([req1, req2])
    assert len(batch_results) == 2
    assert batch_results[0].is_drifted is False
    assert batch_results[1].is_drifted is True

    decorated = manager.decorate_stale_memories(
        contents=[req1.content, req2.content],
        results=batch_results,
    )
    assert len(decorated) == 2
    assert "[⚠️ 过时警告" not in decorated[0]
    assert "[⚠️ 过时警告" in decorated[1]
