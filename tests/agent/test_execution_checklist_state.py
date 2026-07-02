"""Tests for execution checklist state persistence."""

from __future__ import annotations

from pathlib import Path

import pytest

from myrm_agent_harness.agent.execution_checklist.state import (
    ChecklistItem,
    ExecutionChecklistState,
    checklist_exists_sync,
    checklist_file_path,
    merge_checklist_by_id,
    normalize_checklist_items,
    read_checklist_sync,
    resolve_checklist_items,
    save_checklist_to_workspace,
)
from myrm_agent_harness.agent.sub_agents.planner.schemas import Plan, PlanStep
from myrm_agent_harness.agent.sub_agents.planner.storage import read_plan_sync_from_workspace


def test_normalize_checklist_items_assigns_ids() -> None:
    items = normalize_checklist_items([{"content": "Step A", "status": "pending"}])
    assert len(items) == 1
    assert items[0].content == "Step A"
    assert items[0].id.startswith("item_")


@pytest.mark.asyncio
async def test_save_and_read_checklist_workspace_roundtrip(tmp_path: Path) -> None:
    workspace = tmp_path / "sandbox" / "chat_abc"
    workspace.mkdir(parents=True)
    state = ExecutionChecklistState(
        items=[ChecklistItem(id="a", content="Step A", status="pending")],
    )
    await save_checklist_to_workspace(str(workspace), state)
    assert checklist_file_path(str(workspace)).is_file()
    loaded = read_checklist_sync(str(workspace))
    assert loaded is not None
    assert len(loaded.items) == 1
    assert loaded.items[0].content == "Step A"


def test_checklist_exists_sync(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    assert checklist_exists_sync(str(workspace)) is False
    rel = checklist_file_path(str(workspace))
    rel.parent.mkdir(parents=True, exist_ok=True)
    rel.write_text('{"version":1,"items":[]}', encoding="utf-8")
    assert checklist_exists_sync(str(workspace)) is True


def test_merge_checklist_by_id_preserves_unmentioned_items() -> None:
    existing = [
        ChecklistItem(id="a", content="A", status="pending"),
        ChecklistItem(id="b", content="B", status="pending"),
    ]
    incoming = [ChecklistItem(id="a", content="A", status="completed")]
    merged = merge_checklist_by_id(existing, incoming)
    assert len(merged) == 2
    assert merged[0].status == "completed"
    assert merged[1].status == "pending"


def test_resolve_checklist_items_full_replace_when_growing() -> None:
    existing = [ChecklistItem(id="a", content="A", status="pending")]
    incoming = [
        ChecklistItem(id="a", content="A", status="completed"),
        ChecklistItem(id="b", content="B", status="pending"),
    ]
    resolved = resolve_checklist_items(existing, incoming)
    assert len(resolved) == 2
    assert resolved[1].id == "b"


@pytest.mark.asyncio
async def test_workspace_path_differs_from_global_storage(tmp_path: Path) -> None:
    """Guard reads workspace; writes must not land in a separate global storage root."""
    workspace = tmp_path / "sandboxes" / "chat_1"
    global_storage = tmp_path / "global_storage"
    workspace.mkdir(parents=True)
    global_storage.mkdir()

    state = ExecutionChecklistState(items=[ChecklistItem(id="x", content="Do work", status="pending")])
    await save_checklist_to_workspace(str(workspace), state)

    assert read_checklist_sync(str(workspace)) is not None
    assert not (global_storage / ".myrm" / "execution_checklist.json").exists()


def test_read_plan_sync_from_workspace(tmp_path: Path) -> None:
    plan_dir = tmp_path / "planner"
    plan_dir.mkdir()
    plan = Plan(
        goal="Test goal",
        reasoning="Because",
        steps=[
            PlanStep(
                step_id="s1",
                description="Do thing",
                expected_output="Done",
                status="pending",
            )
        ],
    )
    (plan_dir / "plan.json").write_text(plan.model_dump_json(), encoding="utf-8")
    loaded = read_plan_sync_from_workspace(str(tmp_path), storage_prefix="/planner")
    assert loaded is not None
    assert loaded.goal == "Test goal"
    assert len(loaded.steps) == 1


def test_read_plan_sync_missing_returns_none(tmp_path: Path) -> None:
    assert read_plan_sync_from_workspace(str(tmp_path)) is None


def test_read_plan_sync_invalid_json_returns_none(tmp_path: Path) -> None:
    plan_dir = tmp_path / "planner"
    plan_dir.mkdir()
    (plan_dir / "plan.json").write_text("not-json{{{", encoding="utf-8")
    assert read_plan_sync_from_workspace(str(tmp_path), storage_prefix="/planner") is None


def test_read_checklist_sync_invalid_json_returns_none(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    path = checklist_file_path(str(workspace))
    path.parent.mkdir(parents=True)
    path.write_text("{bad json", encoding="utf-8")
    assert read_checklist_sync(str(workspace)) is None


def test_normalize_skips_empty_content() -> None:
    items = normalize_checklist_items([{"content": "  ", "status": "pending"}, {"content": "OK", "status": "pending"}])
    assert len(items) == 1
    assert items[0].content == "OK"


def test_normalize_uses_explicit_id() -> None:
    items = normalize_checklist_items([{"id": "step-1", "content": "Do it", "status": "pending"}])
    assert items[0].id == "step-1"


def test_normalize_deduplicates_colliding_ids() -> None:
    items = normalize_checklist_items(
        [
            {"id": "dup", "content": "First", "status": "pending"},
            {"id": "dup", "content": "Second", "status": "pending"},
        ]
    )
    assert items[0].id == "dup"
    assert items[1].id != "dup"
