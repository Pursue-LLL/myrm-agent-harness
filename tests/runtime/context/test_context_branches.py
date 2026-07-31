"""Tests for context branch manifest."""

from __future__ import annotations

import json

import pytest

import myrm_agent_harness.runtime.context.context_branches as branches_module
from myrm_agent_harness.runtime.context.context_branches import (
    append_context_branch,
    get_context_branch,
    list_context_branches,
)


@pytest.fixture
def persistent_root(tmp_path: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> str:
    root = tmp_path / "persistent"
    root.mkdir()
    monkeypatch.setattr(branches_module, "PERSISTENT_ROOT", str(root))
    return str(root)


def test_list_context_branches_empty(persistent_root: str) -> None:
    assert list_context_branches("chat-1") == []


def test_append_and_list_context_branch(persistent_root: str) -> None:
    record = append_context_branch(
        "chat-1",
        snapshot_path=".context/chat-1/snap-1.jsonl",
        label="Before auth refactor",
    )
    assert record.snapshot_path == ".context/chat-1/snap-1.jsonl"
    assert record.label == "Before auth refactor"

    branches = list_context_branches("chat-1")
    assert len(branches) == 1
    assert branches[0].branch_id == record.branch_id


def test_list_context_branches_empty_session_id(persistent_root: str) -> None:
    assert list_context_branches("") == []


def test_list_context_branches_ignores_corrupt_payload(persistent_root: str) -> None:
    path = branches_module._branch_path("chat-corrupt")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not-json", encoding="utf-8")
    assert list_context_branches("chat-corrupt") == []

    path.write_text(json.dumps({"bad": "shape"}), encoding="utf-8")
    assert list_context_branches("chat-corrupt") == []

    path.write_text(
        json.dumps([{"branch_id": "x", "label": 1, "snapshot_path": "p", "created_at": "t"}]),
        encoding="utf-8",
    )
    assert list_context_branches("chat-corrupt") == []

    path.write_text(
        json.dumps(["not-a-dict", {"branch_id": "ok", "label": "l", "snapshot_path": "p", "created_at": "t"}]),
        encoding="utf-8",
    )
    branches = list_context_branches("chat-corrupt")
    assert len(branches) == 1
    assert branches[0].branch_id == "ok"


def test_append_context_branch_requires_session_id(persistent_root: str) -> None:
    with pytest.raises(ValueError, match="session_id"):
        append_context_branch("", snapshot_path=".context/x.jsonl", label="")


def test_append_context_branch_requires_snapshot_path(persistent_root: str) -> None:
    with pytest.raises(ValueError, match="snapshot_path"):
        append_context_branch("chat-1", snapshot_path="   ", label="")


def test_append_context_branch_evicts_oldest_when_over_cap(
    persistent_root: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import myrm_agent_harness.runtime.context.context_branches as mod

    monkeypatch.setattr(mod, "_MAX_BRANCHES", 2)
    first = append_context_branch("chat-cap", snapshot_path=".context/a.jsonl", label="a")
    second = append_context_branch("chat-cap", snapshot_path=".context/b.jsonl", label="b")
    third = append_context_branch("chat-cap", snapshot_path=".context/c.jsonl", label="c")
    branches = list_context_branches("chat-cap")
    assert len(branches) == 2
    assert branches[0].branch_id == second.branch_id
    assert branches[1].branch_id == third.branch_id
    assert first.branch_id not in {item.branch_id for item in branches}


def test_get_context_branch_returns_record_or_none(persistent_root: str) -> None:
    record = append_context_branch(
        "chat-lookup",
        snapshot_path=".context/snap.jsonl",
        label="lookup",
    )
    assert get_context_branch("chat-lookup", record.branch_id) == record
    assert get_context_branch("chat-lookup", "missing") is None
    assert get_context_branch("", record.branch_id) is None
