from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.agent.meta_tools.file_ops.core.file_operation_service import (
    FileOperationService,
)
from myrm_agent_harness.agent.meta_tools.file_ops.core.operation_context import (
    OperationContext,
    OperationType,
    StrReplaceEdit,
)
from myrm_agent_harness.toolkits.code_execution.executors.models import ExecutionResult


@pytest.fixture
def mock_executor():
    executor = AsyncMock()
    executor.resolve_path = MagicMock(side_effect=lambda p: f"/mock/ws/{p}")
    return executor


class TestVerifyCommand:
    @pytest.mark.asyncio
    async def test_create_verify_success(self, mock_executor):
        mock_executor.execute_bash.return_value = ExecutionResult(
            success=True, exit_code=0, stdout="ok", stderr=""
        )

        ctx = OperationContext(
            operation=OperationType.CREATE,
            path="test.py",
            file_text="print('hello')",
            verify_command="python -m py_compile test.py",
            executor=mock_executor,
        )

        # Mock strategy
        service = FileOperationService(ctx)
        with patch(
            "myrm_agent_harness.agent.meta_tools.file_ops.strategies.strategy_factory.FileSystemStrategyFactory.create_strategy"
        ) as mock_factory:
            mock_strategy = AsyncMock()
            mock_strategy.exists.return_value = False
            mock_strategy.read_file.return_value = ["print('hello')"]
            mock_factory.return_value = mock_strategy

            result = await service._execute_create()

            assert "Successfully created" in result
            mock_executor.execute_bash.assert_awaited_once()
            mock_strategy.delete_file.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_create_verify_failure_deletes_file(self, mock_executor):
        mock_executor.execute_bash.return_value = ExecutionResult(
            success=False, exit_code=1, stdout="", stderr="SyntaxError"
        )

        ctx = OperationContext(
            operation=OperationType.CREATE,
            path="test.py",
            file_text="print('hello')",
            verify_command="python -m py_compile test.py",
            executor=mock_executor,
        )

        service = FileOperationService(ctx)
        with patch(
            "myrm_agent_harness.agent.meta_tools.file_ops.strategies.strategy_factory.FileSystemStrategyFactory.create_strategy"
        ) as mock_factory:
            mock_strategy = AsyncMock()
            mock_strategy.exists.return_value = False
            mock_strategy.read_file.return_value = ["print('hello')"]
            mock_factory.return_value = mock_strategy

            with pytest.raises(
                ValueError, match="File created but verification failed"
            ):
                await service._execute_create()

            mock_executor.execute_bash.assert_awaited_once()
            mock_strategy.delete_file.assert_awaited_once_with("test.py")

    @pytest.mark.asyncio
    async def test_edit_verify_success(self, mock_executor):
        mock_executor.execute_bash.return_value = ExecutionResult(
            success=True, exit_code=0, stdout="ok", stderr=""
        )

        ctx = OperationContext(
            operation=OperationType.STR_REPLACE,
            path="test.py",
            edits=(StrReplaceEdit(old_str="old", new_str="new"),),
            verify_command="python -m py_compile test.py",
            executor=mock_executor,
        )

        service = FileOperationService(ctx)
        with (
            patch(
                "myrm_agent_harness.agent.meta_tools.file_ops.strategies.strategy_factory.FileSystemStrategyFactory.create_strategy"
            ) as mock_factory,
            patch(
                "myrm_agent_harness.agent.meta_tools.file_ops.core.file_operation_service.get_file_integrity_guard",
                return_value=None,
            ),
        ):
            mock_strategy = AsyncMock()
            mock_strategy.exists.return_value = True
            mock_strategy.is_directory.return_value = False
            mock_strategy.get_file_size.return_value = 100
            mock_strategy.read_file.return_value = ["old"]
            mock_factory.return_value = mock_strategy

            result = await service._execute_str_replace()

            assert "Successfully replaced text" in result
            mock_executor.execute_bash.assert_awaited_once()
            mock_strategy.write_file.assert_awaited_once_with("test.py", "new")

    @pytest.mark.asyncio
    async def test_edit_verify_failure_rolls_back(self, mock_executor):
        mock_executor.execute_bash.return_value = ExecutionResult(
            success=False, exit_code=1, stdout="", stderr="SyntaxError"
        )

        ctx = OperationContext(
            operation=OperationType.STR_REPLACE,
            path="test.py",
            edits=(StrReplaceEdit(old_str="old", new_str="new"),),
            verify_command="python -m py_compile test.py",
            executor=mock_executor,
        )

        service = FileOperationService(ctx)
        with (
            patch(
                "myrm_agent_harness.agent.meta_tools.file_ops.strategies.strategy_factory.FileSystemStrategyFactory.create_strategy"
            ) as mock_factory,
            patch(
                "myrm_agent_harness.agent.meta_tools.file_ops.core.file_operation_service.get_file_integrity_guard",
                return_value=None,
            ),
        ):
            mock_strategy = AsyncMock()
            mock_strategy.exists.return_value = True
            mock_strategy.is_directory.return_value = False
            mock_strategy.get_file_size.return_value = 100
            mock_strategy.read_file.return_value = ["old"]
            mock_factory.return_value = mock_strategy

            with pytest.raises(ValueError, match="File edited but verification failed"):
                await service._execute_str_replace()

            mock_executor.execute_bash.assert_awaited_once()
            assert mock_strategy.write_file.await_count == 2
            mock_strategy.write_file.assert_any_await("test.py", "old")
