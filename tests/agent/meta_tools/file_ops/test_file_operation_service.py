"""Unit tests for FileOperationService execute branches and VIEW error handling."""

from __future__ import annotations

import asyncio
import logging
from contextlib import ExitStack
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.agent.config import FileIOConfig
from myrm_agent_harness.agent.context_management.infra.session_lock import (
    reset_current_chat_id,
    set_current_chat_id,
)
from myrm_agent_harness.agent.context_management.tracking.task_metrics import (
    ArchiveRefetchDecision,
    clear_task_metrics,
    create_task_metrics,
    get_task_metrics,
)
from myrm_agent_harness.agent.meta_tools.file_ops.core.archive_restore_guard import (
    parse_archive_restore_block_payload,
)
from myrm_agent_harness.agent.meta_tools.file_ops.core.file_operation_service import (
    FileOperationService,
)
from myrm_agent_harness.agent.meta_tools.file_ops.core.operation_context import (
    OperationContext,
    OperationType,
)
from myrm_agent_harness.agent.meta_tools.file_ops.core.read_semaphore import (
    get_read_semaphore,
)


@pytest.mark.asyncio
async def test_execute_unknown_operation() -> None:
    context = OperationContext(operation=OperationType.VIEW, paths=["test.txt"], executor=None)
    service = FileOperationService(context)
    with (
        patch.object(context, "validate"),
        patch.object(service.context, "operation", new="not_a_real_operation"),
        pytest.raises(ValueError, match="Unknown operation"),
    ):
        await service.execute()


@pytest.mark.asyncio
async def test_execute_create_missing_params() -> None:
    context = OperationContext(
        operation=OperationType.CREATE,
        executor=None,
        path="test.txt",
        file_text=None,
    )
    service = FileOperationService(context)
    with patch.object(context, "validate"), pytest.raises(
        ValueError,
        match="CREATE operation requires 'path' and 'file_text' parameters",
    ):
        await service.execute()


@pytest.mark.asyncio
async def test_execute_str_replace_missing_params() -> None:
    context = OperationContext(
        operation=OperationType.STR_REPLACE,
        executor=None,
        path="test.txt",
        old_str=None,
        new_str="new",
    )
    service = FileOperationService(context)
    with patch.object(context, "validate"), pytest.raises(
        ValueError,
        match=r"STR_REPLACE operation requires 'path', 'old_str' and 'new_str' parameters",
    ):
        await service.execute()


@pytest.mark.asyncio
async def test_execute_view_with_read_error() -> None:
    context = OperationContext(operation=OperationType.VIEW, paths=["error.txt"], executor=None)
    service = FileOperationService(context)
    with (
        patch.object(service, "_view_single_path", side_effect=Exception("Read failure")),
        patch.object(context, "validate"),
    ):
        result = await service.execute()

    assert "Error reading error.txt: Read failure" in result


@pytest.mark.asyncio
async def test_execute_view_directory() -> None:
    context = OperationContext(operation=OperationType.VIEW, paths=["/some/dir"], executor=None)
    service = FileOperationService(context)

    with (
        patch.object(context, "validate"),
        patch(
            "myrm_agent_harness.agent.meta_tools.file_ops.core.file_operation_service.FileSystemStrategyFactory.create_strategy",
        ) as mock_factory,
        patch(
            "myrm_agent_harness.agent.meta_tools.file_ops.core.file_operation_service.ValidatorChain",
        ) as mock_validator,
    ):
        mock_strategy = AsyncMock()
        mock_strategy.is_directory.return_value = True
        mock_strategy.list_directory.return_value = [("file1.txt", False, 128)]
        mock_factory.return_value = mock_strategy
        mock_validator_instance = AsyncMock()
        mock_validator.return_value = mock_validator_instance

        result = await service.execute()

    assert "/some/dir:" in result
    assert "file1.txt" in result


@pytest.mark.asyncio
async def test_get_read_semaphore_fallback_when_no_running_loop() -> None:
    io_config = FileIOConfig(max_concurrent_reads=3)
    with patch(
        "myrm_agent_harness.agent.meta_tools.file_ops.core.file_operation_service.asyncio.get_running_loop",
        side_effect=RuntimeError("no running event loop"),
    ):
        sem = await get_read_semaphore(io_config)
    assert isinstance(sem, asyncio.Semaphore)


@pytest.mark.asyncio
async def test_execute_view_warns_when_paths_exceed_concurrency(caplog: pytest.LogCaptureFixture) -> None:
    io_config = FileIOConfig(max_concurrent_reads=2)
    context = OperationContext(
        operation=OperationType.VIEW,
        paths=["a.txt", "b.txt", "c.txt"],
        executor=None,
    )
    service = FileOperationService(context, io_config=io_config)
    with caplog.at_level(logging.WARNING), patch.object(context, "validate"), patch.object(
        service,
        "_view_single_path",
        new_callable=AsyncMock,
        side_effect=lambda p: f"ok:{p}",
    ):
        await service.execute()
    assert any("Concurrent read count" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_execute_view_regular_file_content() -> None:
    context = OperationContext(operation=OperationType.VIEW, paths=["doc.py"], executor=None)
    service = FileOperationService(context)
    with (
        patch.object(context, "validate"),
        patch(
            "myrm_agent_harness.agent.meta_tools.file_ops.core.file_operation_service.FileSystemStrategyFactory.create_strategy",
        ) as mock_factory,
        patch(
            "myrm_agent_harness.agent.meta_tools.file_ops.core.file_operation_service.ValidatorChain",
        ) as mock_vc,
        patch(
            "myrm_agent_harness.agent.meta_tools.file_ops.core.file_operation_service.get_file_integrity_guard",
            return_value=None,
        ),
    ):
        mock_strategy = AsyncMock()
        mock_strategy.is_directory.return_value = False
        mock_strategy.read_file.return_value = ["alpha", "beta"]
        mock_factory.return_value = mock_strategy
        mock_vc.return_value.validate = AsyncMock()
        result = await service.execute()
    assert "alpha" in result
    assert "beta" in result


@pytest.mark.asyncio
async def test_execute_view_blocks_archive_read_when_budget_denies() -> None:
    context = OperationContext(
        operation=OperationType.VIEW,
        paths=[".context/chat/compacted/result.txt:1-1"],
        executor=None,
    )
    service = FileOperationService(context)
    with (
        patch.object(context, "validate"),
        patch(
            "myrm_agent_harness.agent.meta_tools.file_ops.core.file_operation_service.FileSystemStrategyFactory.create_strategy",
        ) as mock_factory,
        patch(
            "myrm_agent_harness.agent.meta_tools.file_ops.core.file_operation_service.ValidatorChain",
        ) as mock_vc,
        patch(
            "myrm_agent_harness.agent.meta_tools.file_ops.core.file_operation_service.evaluate_archive_refetch_for_path",
            return_value=ArchiveRefetchDecision(
                is_archive_path=True,
                allowed=False,
                recorded=False,
                reason="archive_refetch_path_budget_exceeded",
                message="Archived context restore blocked because this path reached the per-task read limit.",
                suggested_action="Use a narrower line range or continue from the existing archive summary.",
            ),
        ),
    ):
        mock_strategy = AsyncMock()
        mock_strategy.is_directory.return_value = False
        mock_strategy.read_file.return_value = ["archived line"]
        mock_factory.return_value = mock_strategy
        mock_vc.return_value.validate = AsyncMock()
        result = await service.execute()

    assert "Archive restore blocked." in result
    assert '"reason": "archive_refetch_path_budget_exceeded"' in result
    assert '"type": "archive_restore_blocked"' in result
    assert "archived line" not in result


@pytest.mark.asyncio
async def test_execute_view_blocks_large_full_archive_read_with_structured_metrics() -> None:
    chat_id = "chat_file_read_archive_range_required"
    archive_path = f".context/{chat_id}/compacted/result.txt"
    context = OperationContext(
        operation=OperationType.VIEW,
        paths=[archive_path],
        executor=None,
    )
    service = FileOperationService(context)
    token = set_current_chat_id(chat_id)
    create_task_metrics(chat_id)
    try:
        with (
            patch.object(context, "validate"),
            patch(
                "myrm_agent_harness.agent.meta_tools.file_ops.core.file_operation_service.FileSystemStrategyFactory.create_strategy",
            ) as mock_factory,
            patch(
                "myrm_agent_harness.agent.meta_tools.file_ops.core.file_operation_service.ValidatorChain",
            ) as mock_vc,
        ):
            mock_strategy = AsyncMock()
            mock_strategy.is_directory.return_value = False
            mock_strategy.get_file_size.return_value = 40_000
            mock_strategy.read_file.return_value = ["archive payload " * 4000]
            mock_factory.return_value = mock_strategy
            mock_vc.return_value.validate = AsyncMock()

            result = await service.execute()

        metrics = get_task_metrics(chat_id)
        assert "Archive restore blocked." in result
        assert '"reason": "archive_restore_range_required"' in result
        assert '"primary_restore_arg": ".context/chat_file_read_archive_range_required/compacted/result.txt:1-200"' in result
        mock_strategy.read_file.assert_not_awaited()
        assert metrics is not None
        assert metrics.archive_restore_blocked_count == 1
        event = metrics.archive_restore_block_events[0]
        assert event.reason == "archive_restore_range_required"
        assert "chunk_restore_args" in event.suggested_action
    finally:
        reset_current_chat_id(token)
        clear_task_metrics(chat_id)


@pytest.mark.asyncio
async def test_execute_view_fails_closed_when_archive_size_probe_fails() -> None:
    chat_id = "chat_file_read_archive_probe_failed"
    archive_path = f".context/{chat_id}/compacted/result.txt"
    context = OperationContext(
        operation=OperationType.VIEW,
        paths=[archive_path],
        executor=None,
    )
    service = FileOperationService(context)
    token = set_current_chat_id(chat_id)
    try:
        with (
            patch.object(context, "validate"),
            patch(
                "myrm_agent_harness.agent.meta_tools.file_ops.core.file_operation_service.FileSystemStrategyFactory.create_strategy",
            ) as mock_factory,
            patch(
                "myrm_agent_harness.agent.meta_tools.file_ops.core.file_operation_service.ValidatorChain",
            ) as mock_vc,
        ):
            mock_strategy = AsyncMock()
            mock_strategy.is_directory.return_value = False
            mock_strategy.get_file_size.side_effect = OSError("permission denied")
            mock_strategy.read_file.return_value = ["archive payload"]
            mock_factory.return_value = mock_strategy
            mock_vc.return_value.validate = AsyncMock()

            result = await service.execute()

            assert "Archive restore blocked." in result
            assert '"reason": "archive_restore_size_probe_failed"' in result
            payload = parse_archive_restore_block_payload(result)
            assert payload is not None
            assert payload["reason"] == "archive_restore_size_probe_failed"
            assert payload["type"] == "archive_restore_blocked"
            assert "archive payload" not in result
            mock_strategy.read_file.assert_not_awaited()
    finally:
        reset_current_chat_id(token)


@pytest.mark.asyncio
async def test_execute_view_records_read_when_integrity_guard_active() -> None:
    context = OperationContext(operation=OperationType.VIEW, paths=["tracked.py"], executor=None)
    service = FileOperationService(context)
    guard = MagicMock()
    with (
        patch.object(context, "validate"),
        patch(
            "myrm_agent_harness.agent.meta_tools.file_ops.core.file_operation_service.FileSystemStrategyFactory.create_strategy",
        ) as mock_factory,
        patch(
            "myrm_agent_harness.agent.meta_tools.file_ops.core.file_operation_service.ValidatorChain",
        ) as mock_vc,
        patch(
            "myrm_agent_harness.agent.meta_tools.file_ops.core.file_operation_service.get_file_integrity_guard",
            return_value=guard,
        ),
    ):
        mock_strategy = AsyncMock()
        mock_strategy.is_directory.return_value = False
        mock_strategy.read_file.return_value = ["line"]
        mock_factory.return_value = mock_strategy
        mock_vc.return_value.validate = AsyncMock()
        await service.execute()
    guard.record_read.assert_called_once_with("tracked.py", "line")


@pytest.mark.asyncio
async def test_execute_create_appends_conflict_notice() -> None:
    context = OperationContext(
        operation=OperationType.CREATE,
        executor=None,
        path="/w/note.txt",
        file_text="hello\n",
    )
    service = FileOperationService(context)
    with ExitStack() as stack:
        stack.enter_context(patch.object(context, "validate"))
        stack.enter_context(
            patch(
                "myrm_agent_harness.agent.meta_tools.file_ops.utils.path_utils.resolve_file_id_path",
                return_value="/w/note.txt",
            )
        )
        mock_factory = stack.enter_context(
            patch(
                "myrm_agent_harness.agent.meta_tools.file_ops.core.file_operation_service.FileSystemStrategyFactory.create_strategy",
            )
        )
        mock_vc = stack.enter_context(
            patch(
                "myrm_agent_harness.agent.meta_tools.file_ops.core.file_operation_service.ValidatorChain",
            )
        )
        stack.enter_context(
            patch(
                "myrm_agent_harness.agent.meta_tools.file_ops.core.file_operation_service.check_conflict_pre_write",
                return_value="Non-blocking conflict notice",
            )
        )
        stack.enter_context(
            patch(
                "myrm_agent_harness.agent.meta_tools.file_ops.validators.delta_syntax_validator.DeltaSyntaxValidator.validate",
            )
        )
        stack.enter_context(
            patch(
                "myrm_agent_harness.agent.meta_tools.file_ops.core.file_operation_service.get_file_integrity_guard",
                return_value=None,
            )
        )
        stack.enter_context(
            patch.object(
                service.observer_manager,
                "notify_file_created",
                new_callable=AsyncMock,
            )
        )
        strategy = AsyncMock()
        strategy.exists = AsyncMock(return_value=False)
        strategy.read_file = AsyncMock(return_value=["hello"])
        mock_factory.return_value = strategy
        mock_vc.return_value.validate = AsyncMock()
        result = await service.execute()
    assert "Non-blocking conflict notice" in result


@pytest.mark.asyncio
async def test_execute_create_overwrite_triggers_modified_observers() -> None:
    """CREATE on an existing path must notify modify so diff/snapshot are not 'new file only'."""
    context = OperationContext(
        operation=OperationType.CREATE,
        executor=None,
        path="/w/existing.txt",
        file_text="line1\nmodified_line2\nline3\n",
    )
    service = FileOperationService(context)
    with ExitStack() as stack:
        stack.enter_context(patch.object(context, "validate"))
        stack.enter_context(
            patch(
                "myrm_agent_harness.agent.meta_tools.file_ops.utils.path_utils.resolve_file_id_path",
                return_value="/w/existing.txt",
            )
        )
        mock_factory = stack.enter_context(
            patch(
                "myrm_agent_harness.agent.meta_tools.file_ops.core.file_operation_service.FileSystemStrategyFactory.create_strategy",
            )
        )
        mock_vc = stack.enter_context(
            patch(
                "myrm_agent_harness.agent.meta_tools.file_ops.core.file_operation_service.ValidatorChain",
            )
        )
        stack.enter_context(
            patch(
                "myrm_agent_harness.agent.meta_tools.file_ops.core.file_operation_service.check_conflict_pre_write",
                return_value=None,
            )
        )
        stack.enter_context(
            patch(
                "myrm_agent_harness.agent.meta_tools.file_ops.validators.delta_syntax_validator.DeltaSyntaxValidator.validate",
            )
        )
        stack.enter_context(
            patch(
                "myrm_agent_harness.agent.meta_tools.file_ops.core.file_operation_service.get_file_integrity_guard",
                return_value=None,
            )
        )
        mock_mod = stack.enter_context(
            patch.object(
                service.observer_manager,
                "notify_file_modified",
                new_callable=AsyncMock,
            )
        )
        mock_create = stack.enter_context(
            patch.object(
                service.observer_manager,
                "notify_file_created",
                new_callable=AsyncMock,
            )
        )
        strategy = AsyncMock()
        strategy.exists = AsyncMock(return_value=True)
        strategy.read_file = AsyncMock(
            side_effect=[
                ["line1", "line2", "line3"],
                ["line1", "modified_line2", "line3"],
            ]
        )
        mock_factory.return_value = strategy
        mock_vc.return_value.validate = AsyncMock()
        await service.execute()
    mock_mod.assert_awaited_once()
    mock_create.assert_not_awaited()


@pytest.mark.asyncio
async def test_execute_str_replace_delta_failure_rolls_back() -> None:
    context = OperationContext(
        operation=OperationType.STR_REPLACE,
        executor=None,
        path="/w/a.py",
        old_str="old",
        new_str="new",
    )
    service = FileOperationService(context)
    old_flat = "old"
    with ExitStack() as stack:
        stack.enter_context(patch.object(context, "validate"))
        stack.enter_context(
            patch(
                "myrm_agent_harness.agent.meta_tools.file_ops.utils.path_utils.resolve_file_id_path",
                return_value="/w/a.py",
            )
        )
        mock_factory = stack.enter_context(
            patch(
                "myrm_agent_harness.agent.meta_tools.file_ops.core.file_operation_service.FileSystemStrategyFactory.create_strategy",
            )
        )
        mock_vc = stack.enter_context(
            patch(
                "myrm_agent_harness.agent.meta_tools.file_ops.core.file_operation_service.ValidatorChain",
            )
        )
        stack.enter_context(
            patch(
                "myrm_agent_harness.agent.meta_tools.file_ops.core.file_operation_service.get_file_integrity_guard",
                return_value=None,
            )
        )
        stack.enter_context(
            patch(
                "myrm_agent_harness.agent.meta_tools.file_ops.core.file_operation_service.check_conflict_pre_write",
                return_value=None,
            )
        )
        stack.enter_context(
            patch(
                "myrm_agent_harness.agent.meta_tools.file_ops.validators.delta_syntax_validator.DeltaSyntaxValidator.validate",
                side_effect=ValueError("delta failed"),
            )
        )
        strategy = AsyncMock()
        strategy.read_file = AsyncMock(side_effect=[["old"], ["broken"]])
        mock_factory.return_value = strategy
        mock_vc.return_value.validate = AsyncMock()
        with pytest.raises(ValueError, match="delta failed"):
            await service.execute()
        strategy.write_file.assert_awaited_once_with("/w/a.py", old_flat)


@pytest.mark.asyncio
async def test_execute_str_replace_appends_conflict_warning() -> None:
    context = OperationContext(
        operation=OperationType.STR_REPLACE,
        executor=None,
        path="/w/a.py",
        old_str="old",
        new_str="new",
    )
    service = FileOperationService(context)
    guard = MagicMock()
    guard.require_read_before_write.return_value = None
    guard.require_full_read_before_edit.return_value = None
    guard.require_version_match.return_value = None
    guard.record_write = MagicMock()
    with ExitStack() as stack:
        stack.enter_context(patch.object(context, "validate"))
        stack.enter_context(
            patch(
                "myrm_agent_harness.agent.meta_tools.file_ops.utils.path_utils.resolve_file_id_path",
                return_value="/w/a.py",
            )
        )
        mock_factory = stack.enter_context(
            patch(
                "myrm_agent_harness.agent.meta_tools.file_ops.core.file_operation_service.FileSystemStrategyFactory.create_strategy",
            )
        )
        mock_vc = stack.enter_context(
            patch(
                "myrm_agent_harness.agent.meta_tools.file_ops.core.file_operation_service.ValidatorChain",
            )
        )
        stack.enter_context(
            patch(
                "myrm_agent_harness.agent.meta_tools.file_ops.core.file_operation_service.get_file_integrity_guard",
                return_value=guard,
            )
        )
        stack.enter_context(
            patch(
                "myrm_agent_harness.agent.meta_tools.file_ops.core.file_operation_service.check_conflict_pre_write",
                return_value="Concurrent edit notice",
            )
        )
        stack.enter_context(
            patch(
                "myrm_agent_harness.agent.meta_tools.file_ops.validators.delta_syntax_validator.DeltaSyntaxValidator.validate",
            )
        )
        stack.enter_context(
            patch.object(
                service.observer_manager,
                "notify_file_modified",
                new_callable=AsyncMock,
            )
        )
        strategy = AsyncMock()
        strategy.read_file = AsyncMock(
            side_effect=[
                ["old"],
                ["new"],
                ["new_final"],
            ]
        )
        mock_factory.return_value = strategy
        mock_vc.return_value.validate = AsyncMock()
        result = await service.execute()
    assert "Concurrent edit notice" in result
    assert "Stale file warning" not in result


@pytest.mark.asyncio
async def test_execute_str_replace_rejects_unread_file() -> None:
    """Gate rejects edits on files never read in the session."""
    context = OperationContext(
        operation=OperationType.STR_REPLACE,
        executor=None,
        path="/w/unread.py",
        old_str="old",
        new_str="new",
    )
    service = FileOperationService(context)
    guard = MagicMock()
    guard.require_read_before_write.return_value = (
        "File '/w/unread.py' has not been read in this session."
    )
    with ExitStack() as stack:
        stack.enter_context(patch.object(context, "validate"))
        stack.enter_context(
            patch(
                "myrm_agent_harness.agent.meta_tools.file_ops.utils.path_utils.resolve_file_id_path",
                return_value="/w/unread.py",
            )
        )
        stack.enter_context(
            patch(
                "myrm_agent_harness.agent.meta_tools.file_ops.core.file_operation_service.FileSystemStrategyFactory.create_strategy",
            )
        )
        mock_vc = stack.enter_context(
            patch(
                "myrm_agent_harness.agent.meta_tools.file_ops.core.file_operation_service.ValidatorChain",
            )
        )
        stack.enter_context(
            patch(
                "myrm_agent_harness.agent.meta_tools.file_ops.core.file_operation_service.get_file_integrity_guard",
                return_value=guard,
            )
        )
        mock_vc.return_value.validate = AsyncMock()

        from myrm_agent_harness.utils.errors import ToolError

        with pytest.raises(ToolError) as exc_info:
            await service.execute()
        assert "has not been read" in str(exc_info.value)


@pytest.mark.asyncio
async def test_execute_str_replace_rejects_partial_read() -> None:
    """Gate rejects edits after only a partial/range read."""
    context = OperationContext(
        operation=OperationType.STR_REPLACE,
        executor=None,
        path="/w/partial.py",
        old_str="old",
        new_str="new",
    )
    service = FileOperationService(context)
    guard = MagicMock()
    guard.require_read_before_write.return_value = None
    guard.require_full_read_before_edit.return_value = (
        "File '/w/partial.py' was only partially read in this session."
    )
    with ExitStack() as stack:
        stack.enter_context(patch.object(context, "validate"))
        stack.enter_context(
            patch(
                "myrm_agent_harness.agent.meta_tools.file_ops.utils.path_utils.resolve_file_id_path",
                return_value="/w/partial.py",
            )
        )
        stack.enter_context(
            patch(
                "myrm_agent_harness.agent.meta_tools.file_ops.core.file_operation_service.FileSystemStrategyFactory.create_strategy",
            )
        )
        mock_vc = stack.enter_context(
            patch(
                "myrm_agent_harness.agent.meta_tools.file_ops.core.file_operation_service.ValidatorChain",
            )
        )
        stack.enter_context(
            patch(
                "myrm_agent_harness.agent.meta_tools.file_ops.core.file_operation_service.get_file_integrity_guard",
                return_value=guard,
            )
        )
        mock_vc.return_value.validate = AsyncMock()

        from myrm_agent_harness.utils.errors import ToolError

        with pytest.raises(ToolError) as exc_info:
            await service.execute()
        assert "partially read" in str(exc_info.value)


@pytest.mark.asyncio
async def test_execute_str_replace_rejects_stale_version() -> None:
    """Gate rejects edits when on-disk content changed since full read."""
    context = OperationContext(
        operation=OperationType.STR_REPLACE,
        executor=None,
        path="/w/stale.py",
        old_str="old",
        new_str="new",
    )
    service = FileOperationService(context)
    guard = MagicMock()
    guard.require_read_before_write.return_value = None
    guard.require_full_read_before_edit.return_value = None
    guard.require_version_match.return_value = (
        "File '/w/stale.py' has changed on disk since your last read."
    )
    with ExitStack() as stack:
        stack.enter_context(patch.object(context, "validate"))
        stack.enter_context(
            patch(
                "myrm_agent_harness.agent.meta_tools.file_ops.utils.path_utils.resolve_file_id_path",
                return_value="/w/stale.py",
            )
        )
        mock_factory = stack.enter_context(
            patch(
                "myrm_agent_harness.agent.meta_tools.file_ops.core.file_operation_service.FileSystemStrategyFactory.create_strategy",
            )
        )
        mock_vc = stack.enter_context(
            patch(
                "myrm_agent_harness.agent.meta_tools.file_ops.core.file_operation_service.ValidatorChain",
            )
        )
        stack.enter_context(
            patch(
                "myrm_agent_harness.agent.meta_tools.file_ops.core.file_operation_service.get_file_integrity_guard",
                return_value=guard,
            )
        )
        strategy = AsyncMock()
        strategy.read_file = AsyncMock(return_value=["stale on disk"])
        mock_factory.return_value = strategy
        mock_vc.return_value.validate = AsyncMock()

        from myrm_agent_harness.utils.errors import ToolError

        with pytest.raises(ToolError) as exc_info:
            await service.execute()
        assert "changed on disk" in str(exc_info.value)


@pytest.mark.asyncio
async def test_create_triggers_auto_verify_when_no_verify_command() -> None:
    """CREATE without verify_command triggers auto_verify and appends report."""
    executor = AsyncMock()
    context = OperationContext(
        operation=OperationType.CREATE,
        executor=executor,
        path="/workspace/main.py",
        file_text="x: int = 'bad'\n",
        verify_command=None,
    )
    service = FileOperationService(context)

    with ExitStack() as stack:
        stack.enter_context(patch.object(context, "validate"))
        stack.enter_context(
            patch(
                "myrm_agent_harness.agent.meta_tools.file_ops.utils.path_utils.resolve_file_id_path",
                return_value="/workspace/main.py",
            )
        )
        mock_factory = stack.enter_context(
            patch(
                "myrm_agent_harness.agent.meta_tools.file_ops.core.file_operation_service.FileSystemStrategyFactory.create_strategy",
            )
        )
        mock_vc = stack.enter_context(
            patch(
                "myrm_agent_harness.agent.meta_tools.file_ops.core.file_operation_service.ValidatorChain",
            )
        )
        stack.enter_context(
            patch(
                "myrm_agent_harness.agent.meta_tools.file_ops.core.file_operation_service.check_conflict_pre_write",
                return_value=None,
            )
        )
        stack.enter_context(
            patch(
                "myrm_agent_harness.agent.meta_tools.file_ops.validators.delta_syntax_validator.DeltaSyntaxValidator.validate",
            )
        )
        stack.enter_context(
            patch(
                "myrm_agent_harness.agent.meta_tools.file_ops.core.file_operation_service.get_file_integrity_guard",
                return_value=None,
            )
        )
        stack.enter_context(
            patch.object(
                service.observer_manager,
                "notify_file_created",
                new_callable=AsyncMock,
            )
        )
        mock_auto_verify = stack.enter_context(
            patch(
                "myrm_agent_harness.agent.meta_tools.file_ops.validators.auto_verify.run_auto_verify",
                new_callable=AsyncMock,
                return_value="\n[Auto-Verify] Type errors detected, please fix:\n  main.py:1:1 - error: Type mismatch",
            )
        )
        strategy = AsyncMock()
        strategy.exists = AsyncMock(return_value=False)
        strategy.read_file = AsyncMock(return_value=["x: int = 'bad'"])
        mock_factory.return_value = strategy
        mock_vc.return_value.validate = AsyncMock()

        result = await service.execute()

    assert "[Auto-Verify]" in result
    assert "Type mismatch" in result
    mock_auto_verify.assert_called_once_with(executor, "/workspace/main.py")


@pytest.mark.asyncio
async def test_create_skips_auto_verify_when_verify_command_present() -> None:
    """CREATE with explicit verify_command skips auto_verify entirely."""
    executor = AsyncMock()
    exec_result = AsyncMock()
    exec_result.success = True
    exec_result.exit_code = 0
    exec_result.stdout = ""
    exec_result.stderr = ""
    executor.execute_bash.return_value = exec_result

    context = OperationContext(
        operation=OperationType.CREATE,
        executor=executor,
        path="/workspace/main.py",
        file_text="x: int = 1\n",
        verify_command="pyright /workspace/main.py",
    )
    service = FileOperationService(context)

    with ExitStack() as stack:
        stack.enter_context(patch.object(context, "validate"))
        stack.enter_context(
            patch(
                "myrm_agent_harness.agent.meta_tools.file_ops.utils.path_utils.resolve_file_id_path",
                return_value="/workspace/main.py",
            )
        )
        mock_factory = stack.enter_context(
            patch(
                "myrm_agent_harness.agent.meta_tools.file_ops.core.file_operation_service.FileSystemStrategyFactory.create_strategy",
            )
        )
        mock_vc = stack.enter_context(
            patch(
                "myrm_agent_harness.agent.meta_tools.file_ops.core.file_operation_service.ValidatorChain",
            )
        )
        stack.enter_context(
            patch(
                "myrm_agent_harness.agent.meta_tools.file_ops.core.file_operation_service.check_conflict_pre_write",
                return_value=None,
            )
        )
        stack.enter_context(
            patch(
                "myrm_agent_harness.agent.meta_tools.file_ops.validators.delta_syntax_validator.DeltaSyntaxValidator.validate",
            )
        )
        stack.enter_context(
            patch(
                "myrm_agent_harness.agent.meta_tools.file_ops.core.file_operation_service.get_file_integrity_guard",
                return_value=None,
            )
        )
        stack.enter_context(
            patch.object(
                service.observer_manager,
                "notify_file_created",
                new_callable=AsyncMock,
            )
        )
        mock_auto_verify = stack.enter_context(
            patch(
                "myrm_agent_harness.agent.meta_tools.file_ops.validators.auto_verify.run_auto_verify",
                new_callable=AsyncMock,
            )
        )
        strategy = AsyncMock()
        strategy.exists = AsyncMock(return_value=False)
        strategy.read_file = AsyncMock(return_value=["x: int = 1"])
        mock_factory.return_value = strategy
        mock_vc.return_value.validate = AsyncMock()

        result = await service.execute()

    assert "[Auto-Verify]" not in result
    mock_auto_verify.assert_not_called()


@pytest.mark.asyncio
async def test_str_replace_triggers_auto_verify_with_line_range() -> None:
    """STR_REPLACE without verify_command triggers auto_verify with edit range."""
    executor = AsyncMock()
    context = OperationContext(
        operation=OperationType.STR_REPLACE,
        executor=executor,
        path="/workspace/main.py",
        old_str="x = 1",
        new_str="x: str = 1",
        verify_command=None,
    )
    service = FileOperationService(context)

    with ExitStack() as stack:
        stack.enter_context(patch.object(context, "validate"))
        stack.enter_context(
            patch(
                "myrm_agent_harness.agent.meta_tools.file_ops.utils.path_utils.resolve_file_id_path",
                return_value="/workspace/main.py",
            )
        )
        mock_factory = stack.enter_context(
            patch(
                "myrm_agent_harness.agent.meta_tools.file_ops.core.file_operation_service.FileSystemStrategyFactory.create_strategy",
            )
        )
        mock_vc = stack.enter_context(
            patch(
                "myrm_agent_harness.agent.meta_tools.file_ops.core.file_operation_service.ValidatorChain",
            )
        )
        stack.enter_context(
            patch(
                "myrm_agent_harness.agent.meta_tools.file_ops.core.file_operation_service.check_conflict_pre_write",
                return_value=None,
            )
        )
        stack.enter_context(
            patch(
                "myrm_agent_harness.agent.meta_tools.file_ops.core.file_operation_service.get_file_integrity_guard",
                return_value=None,
            )
        )
        stack.enter_context(
            patch(
                "myrm_agent_harness.agent.meta_tools.file_ops.core.file_operation_service.compute_edit_line_range",
                return_value=(5, 5),
            )
        )
        stack.enter_context(
            patch.object(
                service.observer_manager,
                "notify_file_modified",
                new_callable=AsyncMock,
            )
        )
        mock_auto_verify = stack.enter_context(
            patch(
                "myrm_agent_harness.agent.meta_tools.file_ops.validators.auto_verify.run_auto_verify",
                new_callable=AsyncMock,
                return_value="\n[Auto-Verify] Type errors detected, please fix:\n  main.py:5:1 - error: Incompatible types",
            )
        )
        strategy = AsyncMock()
        strategy.exists = AsyncMock(return_value=True)
        strategy.read_file = AsyncMock(return_value=["line1", "line2", "line3", "line4", "x = 1", "line6"])
        mock_factory.return_value = strategy
        mock_vc.return_value.validate = AsyncMock()

        result = await service.execute()

    assert "[Auto-Verify]" in result
    assert "Incompatible types" in result
    mock_auto_verify.assert_called_once_with(
        executor, "/workspace/main.py", edit_line_start=5, edit_line_end=5
    )
