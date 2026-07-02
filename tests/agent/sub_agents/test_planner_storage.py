"""Tests for sub_agents/planner/storage.py — PlannerStorage adapter."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from myrm_agent_harness.agent.sub_agents.planner.schemas import Plan, PlanStep
from myrm_agent_harness.agent.sub_agents.planner.storage import (
    PlannerStorage,
    plan_exists_sync,
    read_plan_sync_from_workspace,
    workspace_load_plan,
    workspace_plan_exists,
)


def _make_plan() -> Plan:
    return Plan(
        goal="Test goal",
        reasoning="Test reasoning",
        steps=[
            PlanStep(step_id="s1", description="Do step 1", expected_output="Result 1"),
            PlanStep(step_id="s2", description="Do step 2", expected_output="Result 2", status="completed"),
        ],
    )


class TestPlannerStorageInit:
    def test_default_prefix(self):
        backend = MagicMock()
        storage = PlannerStorage(backend)
        assert storage.prefix == "/planner"

    def test_custom_prefix(self):
        backend = MagicMock()
        storage = PlannerStorage(backend, prefix="/custom/")
        assert storage.prefix == "/custom"

    def test_get_path(self):
        backend = MagicMock()
        storage = PlannerStorage(backend, prefix="/plans")
        assert storage._get_path("plan.json") == "/plans/plan.json"


class TestPlannerStorageSave:
    async def test_save_plan(self):
        backend = MagicMock()
        storage = PlannerStorage(backend)

        async def mock_write_file(filename, content):
            pass

        storage._write_file = MagicMock(side_effect=mock_write_file)
        plan = _make_plan()
        await storage.save_plan(plan)
        assert storage._write_file.call_count == 3

    async def test_save_plan_error_handling(self):
        backend = MagicMock()
        storage = PlannerStorage(backend)
        storage._write_file = MagicMock(side_effect=OSError("disk full"))
        plan = _make_plan()
        with pytest.raises(RuntimeError, match="Shadow sync"):
            await storage.save_plan(plan)

    async def test_write_file_wraps_storage_errors(self):
        backend = MagicMock()
        backend.write_text = MagicMock(side_effect=OSError("permission denied"))
        storage = PlannerStorage(backend)
        with pytest.raises(RuntimeError, match="Failed to write"):
            await storage._write_file("plan.json", "{}")


class TestPlannerStorageLoad:
    async def test_load_plan_success(self):
        plan = _make_plan()
        backend = MagicMock()

        async def mock_read_text(path):
            return plan.model_dump_json()

        backend.read_text = mock_read_text
        storage = PlannerStorage(backend)
        loaded = await storage.load_plan()
        assert loaded is not None
        assert loaded.goal == "Test goal"

    async def test_load_plan_not_found(self):
        backend = MagicMock()

        async def mock_read_text(path):
            raise FileNotFoundError("not found")

        backend.read_text = mock_read_text
        storage = PlannerStorage(backend)
        loaded = await storage.load_plan()
        assert loaded is None

    async def test_load_plan_invalid_json(self):
        backend = MagicMock()

        async def mock_read_text(path):
            return "not valid json{{{"

        backend.read_text = mock_read_text
        storage = PlannerStorage(backend)
        with pytest.raises(RuntimeError, match="Failed to parse"):
            await storage.load_plan()


class TestStripLineNumbers:
    def test_no_line_numbers(self):
        backend = MagicMock()
        storage = PlannerStorage(backend)
        content = '{"key": "value"}'
        assert storage._strip_line_numbers(content) == content

    def test_with_line_numbers(self):
        backend = MagicMock()
        storage = PlannerStorage(backend)
        content = '     1|{"key": "value"}\n     2|"other": "val"}'
        result = storage._strip_line_numbers(content)
        assert "     1|" not in result
        assert '{"key": "value"}' in result


class TestPlannerStorageDelete:
    async def test_delete_plan_all_exist(self):
        backend = MagicMock()

        async def mock_exists(*args, **kwargs): return True
        async def mock_delete(*args, **kwargs): return True

        backend.exists = mock_exists
        backend.delete = mock_delete
        storage = PlannerStorage(backend)
        result = await storage.delete_plan()
        assert result is True

    async def test_delete_plan_none_exist(self):
        backend = MagicMock()
        async def mock_exists(*args, **kwargs): return False
        backend.exists = mock_exists
        storage = PlannerStorage(backend)
        result = await storage.delete_plan()
        assert result is False


class TestPlannerStorageGetters:
    async def test_plan_exists(self):
        backend = MagicMock()
        async def mock_exists(*args, **kwargs): return True
        backend.exists = mock_exists
        storage = PlannerStorage(backend)
        assert await storage.plan_exists() is True

    async def test_get_summary(self):
        backend = MagicMock()

        async def mock_read_text(path):
            return "Goal: Test\nSteps: 2"

        backend.read_text = mock_read_text
        storage = PlannerStorage(backend)
        summary = await storage.get_summary()
        assert summary is not None
        assert "Goal" in summary

    async def test_get_markdown(self):
        backend = MagicMock()

        async def mock_read_text(path):
            return "# Plan\n## Steps"

        backend.read_text = mock_read_text
        storage = PlannerStorage(backend)
        md = await storage.get_markdown()
        assert md is not None
        assert "# Plan" in md

    async def test_get_summary_not_found(self):
        backend = MagicMock()

        async def mock_read_text(path):
            raise FileNotFoundError("not found")

        backend.read_text = mock_read_text
        storage = PlannerStorage(backend)
        assert await storage.get_summary() is None


class TestWorkspacePlanHelpers:
    async def test_workspace_plan_exists_primary(self):
        backend = MagicMock()

        async def mock_exists(_path: str) -> bool:
            return True

        backend.exists = mock_exists
        assert await workspace_plan_exists(backend, storage_prefix="/planner") is True

    async def test_workspace_plan_exists_prefers_workspace_root(self, tmp_path):
        backend = MagicMock()
        plan_dir = tmp_path / "planner"
        plan_dir.mkdir()
        (plan_dir / "plan.json").write_text('{"goal":"g","reasoning":"r","steps":[]}', encoding="utf-8")
        assert await workspace_plan_exists(
            backend,
            workspace_root=str(tmp_path),
            storage_prefix="/planner",
        ) is True

    async def test_workspace_load_plan_returns_plan(self):
        backend = MagicMock()
        plan_json = _make_plan().model_dump_json()

        async def mock_read_text(path: str) -> str:
            if path == "/planner/plan.json":
                return plan_json
            raise FileNotFoundError(path)

        backend.read_text = mock_read_text
        loaded = await workspace_load_plan(backend, storage_prefix="/planner")
        assert loaded is not None
        assert loaded.goal == "Test goal"


class TestPlannerWorkspaceShadow:
    async def test_save_plan_writes_to_workspace_not_storage(self, tmp_path):
        backend = MagicMock()
        workspace = tmp_path / "chat_ws"
        workspace.mkdir()
        storage = PlannerStorage(backend, workspace_root=str(workspace))
        await storage.save_plan(_make_plan())

        plan_path = workspace / "planner" / "plan.json"
        assert plan_path.is_file()
        assert (workspace / "planner" / "task_plan.md").is_file()
        assert (workspace / "planner" / "plan_summary.txt").is_file()
        backend.write_text.assert_not_called()

    async def test_load_plan_reads_workspace_first(self, tmp_path):
        backend = MagicMock()
        workspace = tmp_path / "chat_ws"
        plan_dir = workspace / "planner"
        plan_dir.mkdir(parents=True)
        plan_dir.joinpath("plan.json").write_text(_make_plan().model_dump_json(), encoding="utf-8")

        storage = PlannerStorage(backend, workspace_root=str(workspace))
        loaded = await storage.load_plan()
        assert loaded is not None
        assert loaded.goal == "Test goal"
        backend.read_text.assert_not_called()

    async def test_plan_exists_sync_and_load_roundtrip(self, tmp_path):
        backend = MagicMock()
        workspace = tmp_path / "ws"
        storage = PlannerStorage(backend, workspace_root=str(workspace))
        await storage.save_plan(_make_plan())

        assert plan_exists_sync(str(workspace), storage_prefix="/planner") is True
        loaded = read_plan_sync_from_workspace(str(workspace), storage_prefix="/planner")
        assert loaded is not None
        assert loaded.goal == "Test goal"

    async def test_completion_guard_sees_workspace_plan_after_save(self, tmp_path):
        from myrm_agent_harness.agent.middlewares.completion_guard import _build_checklist
        from myrm_agent_harness.agent.security.guards.loop_guard_types import CallRecord, SuccessLevel

        backend = MagicMock()
        workspace = tmp_path / "chat_ws"
        workspace.mkdir()
        storage = PlannerStorage(backend, workspace_root=str(workspace))
        await storage.save_plan(_make_plan())

        records = [
            CallRecord(
                tool_name="file_write_tool",
                args_hash="w1",
                args={"path": "/out/app.py", "content": "x"},
                success_level=SuccessLevel.FULL_SUCCESS,
            ),
        ]
        checklist, has_critical = _build_checklist(records, workspace_root=str(workspace))
        assert has_critical
        assert "uncompleted steps in your Goal Plan" in checklist

    async def test_save_plan_workspace_write_failure(self, tmp_path):
        backend = MagicMock()
        workspace = tmp_path / "chat_ws"
        workspace.mkdir()
        storage = PlannerStorage(backend, workspace_root=str(workspace))
        with patch(
            "myrm_agent_harness.agent.sub_agents.planner.storage.save_plan_files_to_workspace",
            side_effect=OSError("disk full"),
        ):
            with pytest.raises(RuntimeError, match="Shadow sync"):
                await storage.save_plan(_make_plan())

    async def test_plan_exists_true_from_workspace_without_storage(self, tmp_path):
        backend = MagicMock()
        workspace = tmp_path / "chat_ws"
        plan_dir = workspace / "planner"
        plan_dir.mkdir(parents=True)
        plan_dir.joinpath("plan.json").write_text('{"goal":"g","reasoning":"r","steps":[]}', encoding="utf-8")
        storage = PlannerStorage(backend, workspace_root=str(workspace))
        assert await storage.plan_exists() is True
        backend.exists.assert_not_called()

    async def test_get_markdown_not_found(self):
        backend = MagicMock()

        async def mock_read_text(path):
            raise FileNotFoundError("not found")

        backend.read_text = mock_read_text
        storage = PlannerStorage(backend)
        assert await storage.get_markdown() is None
