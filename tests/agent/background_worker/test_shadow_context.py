"""Tests for shadow-agent bulkhead isolation."""

from __future__ import annotations

import io
import logging
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from myrm_agent_harness.agent.background_worker.shadow_context import (
    ShadowExecutorMiddleware,
    get_shadow_silent_mode,
    restricted_shadow_context,
)
from myrm_agent_harness.agent.middlewares._session_context import get_is_shadow_agent
from myrm_agent_harness.toolkits.code_execution.executors.base import (
    CodeExecutor,
    ExecutionContext,
    ExecutionResult,
    get_executor,
    reset_executor,
    set_executor,
)


class _RecordingExecutor(CodeExecutor):
    """Minimal executor for shadow middleware tests."""

    def __init__(self, workspace: str) -> None:
        super().__init__()
        self._workspace = workspace
        self.writes: list[str] = []

    @property
    def workspace_path(self) -> str:
        return self._workspace

    def bind_workspace(self, workspace_path: str) -> None:
        self._workspace = workspace_path

    async def execute(self, context: ExecutionContext) -> ExecutionResult:
        return ExecutionResult(success=True, stdout="executed")

    async def execute_bash(self, context: ExecutionContext) -> ExecutionResult:
        return ExecutionResult(success=True, stdout="bash")

    async def resolve_path(self, relative_path: str) -> str:
        return str(Path(self._workspace) / relative_path)

    async def write_file(self, path: str, content: str) -> None:
        self.writes.append(path)


@pytest.fixture
def workspace(tmp_path: Path) -> str:
    ws = tmp_path / "workspace"
    ws.mkdir()
    return str(ws)


@pytest.fixture
def inner_executor(workspace: str) -> _RecordingExecutor:
    executor = _RecordingExecutor(workspace)
    executor.bind_workspace(workspace)
    return executor


@pytest.fixture
def shadow_executor(inner_executor: _RecordingExecutor) -> ShadowExecutorMiddleware:
    return ShadowExecutorMiddleware(inner_executor)


class TestShadowExecutorMiddleware:
    @pytest.mark.asyncio
    async def test_blocks_python_execution(self, shadow_executor: ShadowExecutorMiddleware) -> None:
        ctx = ExecutionContext(code="print(1)", work_dir=shadow_executor.workspace_path)
        with pytest.raises(PermissionError, match="Python execution is blocked"):
            await shadow_executor.execute(ctx)

    @pytest.mark.asyncio
    async def test_blocks_bash_execution(self, shadow_executor: ShadowExecutorMiddleware) -> None:
        ctx = ExecutionContext(code="echo hi", work_dir=shadow_executor.workspace_path)
        with pytest.raises(PermissionError, match="Bash execution is blocked"):
            await shadow_executor.execute_bash(ctx)

    @pytest.mark.asyncio
    async def test_blocks_exec_bash_helper(self, shadow_executor: ShadowExecutorMiddleware) -> None:
        with pytest.raises(PermissionError, match="Bash execution is blocked"):
            await shadow_executor._exec_bash("echo hi")

    @pytest.mark.asyncio
    async def test_allows_context_sidecar_writes(
        self, shadow_executor: ShadowExecutorMiddleware, inner_executor: _RecordingExecutor, workspace: str
    ) -> None:
        allowed = str(Path(workspace) / ".context" / "skills" / "demo" / "SKILL.md")
        await shadow_executor.write_file(allowed, "skill body")
        assert inner_executor.writes == [allowed]

    @pytest.mark.asyncio
    async def test_allows_skill_support_paths(
        self, shadow_executor: ShadowExecutorMiddleware, inner_executor: _RecordingExecutor, workspace: str
    ) -> None:
        allowed = str(Path(workspace) / "skills" / "demo" / "references" / "guide.md")
        await shadow_executor.write_file(allowed, "ref")
        assert inner_executor.writes == [allowed]

    @pytest.mark.asyncio
    async def test_blocks_arbitrary_writes(
        self, shadow_executor: ShadowExecutorMiddleware, workspace: str
    ) -> None:
        blocked = str(Path(workspace) / "src" / "main.py")
        with pytest.raises(PermissionError, match="Write access"):
            await shadow_executor.write_file(blocked, "hack")

    @pytest.mark.asyncio
    async def test_delegates_allowed_writes_to_inner(self, workspace: str) -> None:
        inner = AsyncMock(spec=CodeExecutor)
        inner.config = None
        inner.workspace_path = workspace
        inner.resolve_path = AsyncMock(
            side_effect=lambda path: str(Path(workspace) / path.removeprefix("./"))
        )
        inner.write_file = AsyncMock()
        shadow = ShadowExecutorMiddleware(inner)

        relative = ".context/skills/demo/SKILL.md"
        await shadow.write_file(relative, "body")

        inner.write_file.assert_awaited_once_with(relative, "body")

    @pytest.mark.parametrize(
        ("relative", "allowed"),
        [
            (".context/memory/notes.md", True),
            (".context/system/config.json", True),
            ("skills/foo/SKILL.md", True),
            ("skills/foo/.stats.json", True),
            ("skills/foo/scripts/run.sh", True),
            ("src/main.py", False),
            ("../outside.txt", False),
        ],
    )
    @pytest.mark.asyncio
    async def test_write_path_policy(
        self,
        shadow_executor: ShadowExecutorMiddleware,
        inner_executor: _RecordingExecutor,
        workspace: str,
        relative: str,
        allowed: bool,
    ) -> None:
        path = str(Path(workspace) / relative)
        if allowed:
            await shadow_executor.write_file(path, "ok")
            assert path in inner_executor.writes
        else:
            with pytest.raises(PermissionError):
                await shadow_executor.write_file(path, "nope")


class TestRestrictedShadowContext:
    @pytest.mark.asyncio
    async def test_sets_and_restores_shadow_flag(self, inner_executor: _RecordingExecutor) -> None:
        assert get_is_shadow_agent() is False
        executor_token = set_executor(inner_executor)
        try:
            async with restricted_shadow_context():
                assert get_is_shadow_agent() is True
                wrapped = get_executor()
                assert isinstance(wrapped, ShadowExecutorMiddleware)
            assert get_is_shadow_agent() is False
            assert get_executor() is inner_executor
        finally:
            reset_executor(executor_token)

    @pytest.mark.asyncio
    async def test_suppress_logs_flag(self) -> None:
        assert get_shadow_silent_mode() is False
        async with restricted_shadow_context(suppress_logs=True):
            assert get_shadow_silent_mode() is True
        assert get_shadow_silent_mode() is False

    @pytest.mark.asyncio
    async def test_silent_filter_drops_logs(self) -> None:
        root = logging.getLogger()
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        root.addHandler(handler)
        root.setLevel(logging.INFO)
        try:
            async with restricted_shadow_context(suppress_logs=True):
                root.info("shadow noise")
            root.info("visible after")
        finally:
            root.removeHandler(handler)

        output = stream.getvalue()
        assert "shadow noise" not in output
        assert "visible after" in output
