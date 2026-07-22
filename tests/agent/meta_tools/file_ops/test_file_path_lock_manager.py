from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

import pytest

from myrm_agent_harness.agent.meta_tools.file_ops.core.file_operation_service import (
    FileOperationService,
)
from myrm_agent_harness.agent.meta_tools.file_ops.core.file_path_lock_manager import (
    acquire_file_path_lock,
)
from myrm_agent_harness.agent.meta_tools.file_ops.core.operation_context import (
    OperationContext,
    OperationType,
)


@pytest.mark.asyncio
async def test_file_path_lock_serializes_same_path_writes() -> None:
    active_count = 0
    overlap_detected = False
    counter_lock = asyncio.Lock()

    async def worker() -> None:
        nonlocal active_count, overlap_detected
        async with acquire_file_path_lock("src/a.ts"):
            async with counter_lock:
                active_count += 1
                if active_count > 1:
                    overlap_detected = True
            await asyncio.sleep(0.02)
            async with counter_lock:
                active_count -= 1

    await asyncio.gather(worker(), worker())
    assert not overlap_detected


@pytest.mark.asyncio
async def test_file_path_lock_allows_different_paths_in_parallel() -> None:
    active_count = 0
    overlap_detected = False
    counter_lock = asyncio.Lock()

    async def worker(path: str) -> None:
        nonlocal active_count, overlap_detected
        async with acquire_file_path_lock(path):
            async with counter_lock:
                active_count += 1
                if active_count > 1:
                    overlap_detected = True
            await asyncio.sleep(0.02)
            async with counter_lock:
                active_count -= 1

    await asyncio.gather(worker("src/a.ts"), worker("src/b.ts"))
    assert overlap_detected


@pytest.mark.asyncio
async def test_file_path_lock_serializes_symlink_aliases(tmp_path) -> None:
    real_path = tmp_path / "real.ts"
    alias_path = tmp_path / "alias.ts"
    real_path.write_text("hello", encoding="utf-8")
    try:
        alias_path.symlink_to(real_path)
    except (NotImplementedError, OSError):
        pytest.skip("Symlink not supported on this platform")

    active_count = 0
    overlap_detected = False
    counter_lock = asyncio.Lock()

    async def worker(path: str) -> None:
        nonlocal active_count, overlap_detected
        async with acquire_file_path_lock(path):
            async with counter_lock:
                active_count += 1
                if active_count > 1:
                    overlap_detected = True
            await asyncio.sleep(0.02)
            async with counter_lock:
                active_count -= 1

    await asyncio.gather(worker(str(real_path)), worker(str(alias_path)))
    assert not overlap_detected


@pytest.mark.asyncio
async def test_file_operation_service_create_uses_resolved_path_lock() -> None:
    context = OperationContext(
        operation=OperationType.CREATE,
        executor=None,
        path="@file_001",
        file_text="hello",
    )
    service = FileOperationService(context)
    locked_paths: list[str] = []

    @asynccontextmanager
    async def fake_lock(path: str):
        locked_paths.append(path)
        yield path

    with (
        patch.object(context, "validate"),
        patch(
            "myrm_agent_harness.agent.meta_tools.file_ops.utils.path_utils.resolve_file_id_path",
            return_value="/tmp/workspace/a.ts",
        ),
        patch(
            "myrm_agent_harness.agent.meta_tools.file_ops.core.file_operation_service.acquire_file_path_lock",
            fake_lock,
        ),
        patch.object(service, "_execute_create", new=AsyncMock(return_value="created")),
    ):
        result = await service.execute()

    assert result == "created"
    assert locked_paths == ["/tmp/workspace/a.ts"]


@pytest.mark.asyncio
async def test_file_operation_service_replace_uses_resolved_path_lock() -> None:
    context = OperationContext(
        operation=OperationType.STR_REPLACE,
        executor=None,
        path="@file_002",
        old_str="old",
        new_str="new",
    )
    service = FileOperationService(context)
    locked_paths: list[str] = []

    @asynccontextmanager
    async def fake_lock(path: str):
        locked_paths.append(path)
        yield path

    with (
        patch.object(context, "validate"),
        patch(
            "myrm_agent_harness.agent.meta_tools.file_ops.utils.path_utils.resolve_file_id_path",
            return_value="/tmp/workspace/b.ts",
        ),
        patch(
            "myrm_agent_harness.agent.meta_tools.file_ops.core.file_operation_service.acquire_file_path_lock",
            fake_lock,
        ),
        patch.object(service, "_execute_str_replace", new=AsyncMock(return_value="replaced")),
    ):
        result = await service.execute()

    assert result == "replaced"
    assert locked_paths == ["/tmp/workspace/b.ts"]

