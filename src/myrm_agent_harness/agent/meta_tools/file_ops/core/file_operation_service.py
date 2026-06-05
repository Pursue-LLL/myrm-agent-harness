"""文件操作服务

1. 本文件的 INPUT/OUTPUT/POS 注释

[INPUT]
- strategies.strategy_factory::FileSystemStrategyFactory (POS: 文件系统策略工厂)
- validators.validator_chain::ValidatorChain (POS: 验证器链)
- observers.observer_manager::ObserverManager (POS: 观察者管理器)
- observers.snapshot_observer::SnapshotObserver (POS: 文件快照观察者,撤销支持)
- observers.format_observer::FormatObserver (POS: 编辑后自动格式化)
- observers.artifact_observer::ArtifactObserver (POS: 工件追踪)
- observers.diff_collector::DiffCollectorObserver (POS: 实时 diff 推送)
- observers.tracker_observer::TrackerObserver (POS: 生命周期记录)
- observers.activity_observer::FileActivityObserver (POS: 文件活动记录,并发冲突感知)
- operation_context::OperationContext, OperationType (POS: 操作上下文和类型)
- result_formatter::ResultFormatter, FileContent, DirectoryListing (POS: 结果格式化器)
- staleness_guard::get_staleness_guard (POS: 文件过期检测)
- file_activity_tracker::get_file_activity_tracker (POS: 文件活动跟踪器,行级冲突检测)
- context_management.infra.session_lock::get_current_chat_id (POS: 当前会话上下文)
- utils.token_estimation::estimate_content_tokens (POS: 文件内容 token 估算)
- context_management.tracking.task_metrics::ArchiveRefetchDecision, evaluate_archive_refetch_for_path (POS: 归档上下文读取预算)
- core.archive_restore_guard::evaluate_archive_full_read_before_content, format_archive_restore_block (POS: 归档恢复读取守卫)
- core.file_conflict_guard::check_conflict_pre_write, compute_edit_line_range (POS: 文件并发编辑冲突守卫)
- core.read_semaphore::get_read_semaphore (POS: 读取并发控制)

[OUTPUT]
- FileOperationService: 文件操作服务类(统一的文件操作接口).CREATE 若覆盖已存在路径则
  notify_file_modified(pre_disk, post_write);否则 notify_file_created(post_write).

[POS]
File operation service. Provides a unified file operation interface integrating strategies, validator chains, observer pipelines, archive restore read guards, concurrency control, resource limits, security validation, and concurrent subagent conflict detection.

"""

from __future__ import annotations

import asyncio
import logging

from myrm_agent_harness.agent.config import DEFAULT_FILE_IO_CONFIG, FileIOConfig
from myrm_agent_harness.agent.context_management.infra.session_lock import (
    get_current_chat_id,
)
from myrm_agent_harness.agent.context_management.tracking.task_metrics import (
    evaluate_archive_refetch_for_path,
)
from myrm_agent_harness.utils.token_estimation import (
    estimate_content_tokens,
)

from ..observers.activity_observer import FileActivityObserver
from ..observers.artifact_observer import ArtifactObserver
from ..observers.diff_collector import DiffCollectorObserver
from ..observers.format_observer import FormatObserver
from ..observers.observer_manager import ObserverManager
from ..observers.snapshot_observer import SnapshotObserver
from ..observers.tracker_observer import TrackerObserver
from ..strategies.strategy_factory import FileSystemStrategyFactory
from ..utils.file_utils import parse_path_with_range
from ..validators.validator_chain import ValidatorChain
from .archive_restore_guard import (
    evaluate_archive_full_read_before_content,
    format_archive_restore_block,
)
from .file_conflict_guard import check_conflict_pre_write, compute_edit_line_range
from .operation_context import OperationContext, OperationType
from .read_semaphore import get_read_semaphore
from .result_formatter import DirectoryListing, FileContent, ResultFormatter
from .staleness_guard import get_staleness_guard

logger = logging.getLogger(__name__)


class FileOperationService:
    """文件操作服务

    核心服务类,整合:
    - 文件系统策略(本地/WorkspaceFS/MCP)
    - 验证器链(路径/大小/权限/敏感文件)
    - 观察者模式(Artifact/Tracker/DiffCollector)
    - 安全控制(并发限制、资源限制)
    """

    def __init__(self, context: OperationContext, io_config: FileIOConfig | None = None) -> None:
        """初始化服务

        Args:
            context: 操作上下文
            io_config: I/O 配置(可选,默认使用全局配置)
        """
        self.context = context
        self.io_config = io_config or DEFAULT_FILE_IO_CONFIG
        self.observer_manager = ObserverManager()

        # Observer registration order matters:
        # 1. SnapshotObserver FIRST — captures original content before any modification
        # 2. ArtifactObserver — registers artifacts
        # 3. TrackerObserver — records lifecycle
        # 4. FormatObserver — auto-formats after write (must run before DiffCollector)
        # 5. DiffCollectorObserver — emits real-time diffs (sees formatted content)
        # 6. FileActivityObserver — records write activity for concurrent conflict detection
        self.observer_manager.register(SnapshotObserver())
        self.observer_manager.register(ArtifactObserver())
        self.observer_manager.register(TrackerObserver())
        self.observer_manager.register(FormatObserver())
        self.observer_manager.register(DiffCollectorObserver())
        self.observer_manager.register(FileActivityObserver())

    async def execute(self) -> str:
        """执行文件操作

        Returns:
            操作结果

        Raises:
            ValueError: 参数错误
            FileNotFoundError: 文件不存在
            PermissionError: 权限不足
        """
        # 验证上下文参数
        self.context.validate()

        # 根据操作类型分发
        if self.context.operation == OperationType.VIEW:
            return await self._execute_view()
        elif self.context.operation == OperationType.CREATE:
            return await self._execute_create()
        elif self.context.operation == OperationType.STR_REPLACE:
            return await self._execute_str_replace()
        else:
            raise ValueError(f"Unknown operation: {self.context.operation}")

    async def _execute_view(self) -> str:
        """执行 VIEW 操作(支持批量并发读取,带并发限制)"""
        #  安全性:限制并发读取数量
        if len(self.context.paths) > self.io_config.max_concurrent_reads:
            logger.warning(
                f"Concurrent read count ({len(self.context.paths)}) exceeds limit "
                f"({self.io_config.max_concurrent_reads}). Processing in batches."
            )

        # 获取当前事件循环的读取信号量
        semaphore = await get_read_semaphore(self.io_config)

        # 使用信号量控制并发读取
        async def _read_with_semaphore(path_str: str) -> str | Exception:
            async with semaphore:
                try:
                    return await self._view_single_path(path_str)
                except Exception as e:
                    return e

        # 并发读取多个文件
        tasks = [_read_with_semaphore(path_str) for path_str in self.context.paths]
        results = await asyncio.gather(*tasks)

        # 处理异常
        formatted_results: list[str] = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                path_str = self.context.paths[i]
                error_msg = f" Error reading {path_str}: {result}"
                formatted_results.append(error_msg)
                logger.error(error_msg, exc_info=result)
            else:
                formatted_results.append(result)

        # 格式化多个结果
        return ResultFormatter.format_multiple_results(formatted_results)

    async def _view_single_path(self, path_str: str) -> str:
        """查看单个路径

        Args:
            path_str: 路径字符串(可能包含行号范围)

        Returns:
            格式化后的内容
        """
        # 解析路径和行号范围
        resolved_path, view_range = parse_path_with_range(path_str)

        # 提取显示路径(不含行号范围)
        display_path = path_str.split(":")[0] if ":" in path_str else path_str

        # 创建策略
        strategy = FileSystemStrategyFactory.create_strategy(
            resolved_path, self.context.skills, executor=self.context.executor
        )

        # 验证(使用安全配置)
        validator_chain = ValidatorChain(strategy, io_config=self.io_config)
        await validator_chain.validate(self.context, resolved_path)

        # 检查是否是目录
        if await strategy.is_directory(resolved_path):
            entries = await strategy.list_directory(resolved_path)
            listing = DirectoryListing(path=resolved_path, display_path=display_path, entries=entries)
            return ResultFormatter.format_directory_listing(listing)

        pre_read_archive_decision = await evaluate_archive_full_read_before_content(
            strategy=strategy,
            resolved_path=resolved_path,
            view_range=view_range,
        )
        if pre_read_archive_decision is not None:
            decision, estimated_content_tokens = pre_read_archive_decision
            return format_archive_restore_block(
                decision,
                archive_path=resolved_path,
                estimated_tokens=estimated_content_tokens,
            )

        # 读取文件
        lines = await strategy.read_file(resolved_path, view_range)
        content_text = "\n".join(lines)
        estimated_content_tokens = estimate_content_tokens(content_text)
        archive_refetch_decision = evaluate_archive_refetch_for_path(
            resolved_path,
            estimated_tokens=estimated_content_tokens,
            current_chat_id=get_current_chat_id(),
            is_range_read=view_range is not None,
        )
        if archive_refetch_decision.is_archive_path and not archive_refetch_decision.allowed:
            return format_archive_restore_block(
                archive_refetch_decision,
                archive_path=resolved_path,
                estimated_tokens=estimated_content_tokens,
            )

        guard = get_staleness_guard(self.context.executor)
        if guard is not None:
            if view_range is None:
                guard.record_read(resolved_path, content_text)
            else:
                guard.record_read_marker(resolved_path)

        # 通知观察者
        await self.observer_manager.notify_file_viewed(resolved_path)

        # 格式化输出
        content = FileContent(
            path=resolved_path,
            display_path=display_path,
            lines=lines,
            view_range=view_range,
        )
        return ResultFormatter.format_file_content(content)

    async def _execute_create(self) -> str:
        """执行 CREATE 操作"""
        logger.info("_execute_create called for path: %s", self.context.path)

        if not self.context.path or self.context.file_text is None:
            raise ValueError("CREATE operation requires 'path' and 'file_text' parameters")

        # 解析文件 ID
        from ..utils.path_utils import resolve_file_id_path

        resolved_path = resolve_file_id_path(self.context.path)

        # 创建策略
        strategy = FileSystemStrategyFactory.create_strategy(
            resolved_path, self.context.skills, executor=self.context.executor
        )

        # 验证(使用安全配置)
        validator_chain = ValidatorChain(strategy, io_config=self.io_config)
        await validator_chain.validate(self.context, resolved_path)

        # Concurrent subagent conflict detection (pre-write)
        conflict_warning = check_conflict_pre_write(resolved_path, 1, self.context.file_text.count("\n") + 1)

        pre_existing = await strategy.exists(resolved_path)
        pre_content_str: str | None = None
        original_eol: str | None = None
        if pre_existing:
            pre_content_str = "\n".join(await strategy.read_file(resolved_path))
            from ..utils.line_endings import detect_line_ending, normalize_line_endings

            original_eol = detect_line_ending(pre_content_str)

        file_text = self.context.file_text
        if pre_existing and original_eol:
            file_text = normalize_line_endings(file_text, original_eol)

        # 增量容错语法校验 (Delta Syntax Validator)
        from ..validators.delta_syntax_validator import DeltaSyntaxValidator

        DeltaSyntaxValidator.validate(resolved_path, file_text, pre_content=pre_content_str)

        # 写入文件
        await strategy.write_file(resolved_path, file_text)

        new_content = "\n".join(await strategy.read_file(resolved_path))

        if pre_existing and pre_content_str is not None:
            logger.info(
                "Calling observer_manager.notify_file_modified (CREATE overwrote existing) for %s",
                resolved_path,
            )
            await self.observer_manager.notify_file_modified(resolved_path, pre_content_str, new_content)
        else:
            logger.info("Calling observer_manager.notify_file_created for %s", resolved_path)
            await self.observer_manager.notify_file_created(resolved_path, new_content)

        # 执行自动校验(如果有)
        if self.context.verify_command and self.context.executor:
            from myrm_agent_harness.toolkits.code_execution.executors.models import (
                ExecutionContext,
            )

            logger.info(f"Running verify_command on {resolved_path}: {self.context.verify_command}")
            exec_ctx = ExecutionContext(code=self.context.verify_command, work_dir=".")
            result = await self.context.executor.execute_bash(exec_ctx)

            if not result.success:
                # 校验失败,删除刚创建的文件
                await strategy.delete_file(resolved_path)
                logger.warning(f"Verification failed for {resolved_path}, file deleted. Error: {result.stderr}")
                raise ValueError(
                    f"File created but verification failed. The file has been deleted.\n"
                    f"Command: {self.context.verify_command}\n"
                    f"Exit code: {result.exit_code}\n"
                    f"Stdout: {result.stdout}\n"
                    f"Stderr: {result.stderr}\n"
                    f"Please fix the errors and try again."
                )

        # Smart Auto-Verify fallback (soft diagnostic, no rollback)
        auto_verify_report: str | None = None
        if not self.context.verify_command and self.context.executor:
            from ..validators.auto_verify import run_auto_verify

            auto_verify_report = await run_auto_verify(self.context.executor, resolved_path)

        # Record hash AFTER observers and verification so FormatObserver's changes are captured.
        # Re-read to get the post-formatted content; skip re-read when no
        # executor is available (guard would be None anyway).
        guard = get_staleness_guard(self.context.executor)
        if guard is not None:
            final_content = "\n".join(await strategy.read_file(resolved_path))
            guard.record_write(resolved_path, final_content)

        logger.info(f"Created file: {resolved_path}")

        response = ResultFormatter.format_success("created", resolved_path)
        if conflict_warning:
            response = f"{response}\n\n{conflict_warning}"
        if auto_verify_report:
            response = f"{response}\n{auto_verify_report}"
        return response

    async def _execute_str_replace(self) -> str:
        """执行 STR_REPLACE 操作"""
        if not self.context.path or self.context.old_str is None or self.context.new_str is None:
            raise ValueError("STR_REPLACE operation requires 'path', 'old_str' and 'new_str' parameters")

        # 解析文件 ID
        from ..utils.path_utils import resolve_file_id_path

        resolved_path = resolve_file_id_path(self.context.path)

        # 创建策略
        strategy = FileSystemStrategyFactory.create_strategy(
            resolved_path, self.context.skills, executor=self.context.executor
        )

        # 验证(使用安全配置)
        validator_chain = ValidatorChain(strategy, io_config=self.io_config)
        await validator_chain.validate(self.context, resolved_path)

        # Read-before-edit gate + staleness detection (single guard lookup)
        guard = get_staleness_guard(self.context.executor)
        if guard is not None:
            gate_rejection = guard.require_read_before_write(resolved_path)
            if gate_rejection is not None:
                from myrm_agent_harness.utils.errors import ToolError

                raise ToolError(
                    message=gate_rejection,
                    user_hint="Read the file first with file_read_tool before editing.",
                )

        # 读取原内容
        old_content = "\n".join(await strategy.read_file(resolved_path))

        # 过期检测(复用已读取的 old_content,零额外 I/O)
        staleness_warning: str | None = None
        if guard is not None:
            staleness_warning = guard.check_staleness(resolved_path, old_content)

        # Concurrent subagent conflict detection (line-level precision)
        line_start, line_end = compute_edit_line_range(old_content, self.context.old_str)
        conflict_warning = check_conflict_pre_write(resolved_path, line_start, line_end)

        # 替换文本 (允许 Fuzzy Match 发挥作用)
        await strategy.replace_text(resolved_path, self.context.old_str, self.context.new_str)

        # 读取真实的写后新内容
        new_content = "\n".join(await strategy.read_file(resolved_path))

        # 增量容错语法校验 (Delta Syntax Validator - Execute-then-Rollback 模式)
        from ..validators.delta_syntax_validator import DeltaSyntaxValidator

        try:
            DeltaSyntaxValidator.validate(resolved_path, new_content, pre_content=old_content)
        except ValueError as e:
            # 校验失败,回滚文件内容 (对观察者绝对透明,因为它们还未触发)
            await strategy.write_file(resolved_path, old_content)
            logger.warning(f"Delta Syntax Validation failed for {resolved_path}, changes rolled back. Error: {e}")
            raise

        # 通知观察者(FormatObserver may modify the file on disk)
        await self.observer_manager.notify_file_modified(resolved_path, old_content, new_content)

        # 执行自动校验(如果有)
        if self.context.verify_command and self.context.executor:
            from myrm_agent_harness.toolkits.code_execution.executors.models import (
                ExecutionContext,
            )

            logger.info(f"Running verify_command on {resolved_path}: {self.context.verify_command}")
            exec_ctx = ExecutionContext(code=self.context.verify_command, work_dir=".")
            result = await self.context.executor.execute_bash(exec_ctx)

            if not result.success:
                # 校验失败,回滚文件内容
                await strategy.write_file(resolved_path, old_content)
                logger.warning(f"Verification failed for {resolved_path}, changes rolled back. Error: {result.stderr}")
                raise ValueError(
                    f"File edited but verification failed. Changes have been rolled back.\n"
                    f"Command: {self.context.verify_command}\n"
                    f"Exit code: {result.exit_code}\n"
                    f"Stdout: {result.stdout}\n"
                    f"Stderr: {result.stderr}\n"
                    f"Please fix the errors and try again."
                )

        # Smart Auto-Verify fallback (soft diagnostic, no rollback)
        auto_verify_report: str | None = None
        if not self.context.verify_command and self.context.executor:
            from ..validators.auto_verify import run_auto_verify

            auto_verify_report = await run_auto_verify(
                self.context.executor,
                resolved_path,
                edit_line_start=line_start,
                edit_line_end=line_end,
            )

        # Record hash AFTER observers and verification so FormatObserver's changes are captured.
        # Re-read to get the post-formatted content.
        if guard is not None:
            final_content = "\n".join(await strategy.read_file(resolved_path))
            guard.record_write(resolved_path, final_content)

        logger.info(f"Replaced text in file: {resolved_path}")

        response = ResultFormatter.format_success("replaced text in", resolved_path)
        if staleness_warning:
            response = f"{response}\n\n{staleness_warning}"
        if conflict_warning:
            response = f"{response}\n\n{conflict_warning}"
        if auto_verify_report:
            response = f"{response}\n{auto_verify_report}"
        return response
