"""文件搜索工具（Claude Code 兼容）

1. 本文件的 INPUT/OUTPUT/POS 注释

[INPUT]
- langchain.tools::tool (POS: LangChain 工具装饰器)
- pydantic::BaseModel, Field (POS: 参数验证)
- agent.config.file_io::FileIOConfig (POS: I/O 配置)
- agent.meta_tools._context_recovery::ensure_executor (POS: Executor ContextVar recovery)
- toolkits.storage.base::StorageProvider (POS: 存储协议/接口)
- fallback_discovery::collect_candidate_files (POS: 无 ripgrep 时的候选文件发现与 git-aware ignore 策略)

[OUTPUT]
- GlobInput: Glob 工具输入参数模型
- create_glob_tool: 创建 Glob 工具的工厂函数

[POS]
File search tool (Claude Code compatible). Searches for files using glob patterns (* and **) with recursive search, exclusion patterns, resource limits, and audit logging.

"""

from __future__ import annotations

import contextlib
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from langchain.tools import tool
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field

from myrm_agent_harness.agent.config import DEFAULT_FILE_IO_CONFIG, FileIOConfig
from myrm_agent_harness.agent.meta_tools._context_recovery import ensure_executor
from myrm_agent_harness.utils.errors import ToolError
from myrm_agent_harness.utils.locale import is_chinese

from .fallback_discovery import collect_candidate_files
from .path_hint import format_path_not_found_hint, suggest_similar_paths
from .skill_path_filter import get_disabled_skill_roots, is_under_disabled_skill_root

if TYPE_CHECKING:
    from langchain_core.tools import BaseTool


logger = logging.getLogger(__name__)


class GlobInput(BaseModel):
    """Glob 工具输入参数"""

    pattern: str = Field(description="文件匹配模式（支持 * 和 ** 通配符）")
    path: str = Field(default=".", description="搜索路径（默认当前目录）")
    include_ignored: bool = Field(default=False, description="是否包含被 .gitignore 忽略的文件（默认 False）")


def resolve_glob_tool_description(
    io_cfg: FileIOConfig,
    locale: str | None = None,
) -> str:
    """Resolve LLM-facing glob_tool description."""
    if is_chinese(locale):
        return f"""搜索匹配的文件（支持通配符）。Output: one file path per line.

用途：
- 查找特定类型的文件
- 批量文件搜索
- 项目结构探索

参数：
- pattern: 匹配模式（支持 * 和 **），必需
  * `*`: 匹配任意字符（不包括 /）
  * `**`: 匹配任意层级目录
- path: 搜索路径（默认当前目录）
- include_ignored: 是否包含被 .gitignore 忽略的文件（默认 False）

示例：
- 找所有 Python 文件：glob_tool(pattern="**/*.py")
- 找测试文件：glob_tool(pattern="**/test_*.py")
- 找特定目录下的 JS 文件：glob_tool(pattern="*.js", path="src")
- 找所有配置文件：glob_tool(pattern="**/*.{{yaml,yml,json}}")

限制：
- 最多返回 {io_cfg.max_search_results} 个结果
- 只返回文件，不包括目录

注意：
- 使用 ** 进行递归搜索
- 搜索结果按路径排序
"""
    return f"""Search for matching files using glob patterns. Output: one file path per line.

Use cases:
- Find specific file types
- Batch file search
- Project structure exploration

Parameters:
- pattern: Match pattern (supports * and **), required
  * `*`: matches any characters (excluding /)
  * `**`: matches directories across arbitrary levels
- path: Search directory (default '.')
- include_ignored: Whether to include files ignored by .gitignore (default False)

Examples:
- Find all Python files: glob_tool(pattern="**/*.py")
- Find test files: glob_tool(pattern="**/test_*.py")
- Find JS files in directory: glob_tool(pattern="*.js", path="src")
- Find config files: glob_tool(pattern="**/*.{{yaml,yml,json}}")

Limits:
- Returns at most {io_cfg.max_search_results} results
- Only returns files, not directories

Notes:
- Use ** for recursive search
- Search results are sorted by path
"""


def create_glob_tool(
    io_config: FileIOConfig | None = None,
    *,
    locale: str | None = None,
) -> BaseTool:
    """创建文件搜索工具

    从 context 动态获取 executor 进行路径解析。

    Args:
        io_config: 文件 IO 配置（可选）
        locale: 提示词语言

    Returns:
        glob_tool 工具函数
    """
    io_cfg = io_config or DEFAULT_FILE_IO_CONFIG

    @tool(
        "glob_tool",
        description=resolve_glob_tool_description(io_cfg, locale),
        args_schema=GlobInput,
    )
    async def glob_func(
        pattern: str,
        path: str = ".",
        include_ignored: bool = False,
        *,
        config: RunnableConfig,  #  纯净设计：从 config 获取 context
    ) -> str:
        """搜索匹配的文件

        Args:
            pattern: 文件匹配模式
            path: 搜索路径
            include_ignored: 是否包含被 .gitignore 忽略的文件
            config: LangChain 运行时配置（自动注入）

        Returns:
            匹配的文件列表

        Raises:
            FileNotFoundError: 搜索路径不存在
            PermissionError: 权限不足
            ValueError: 路径不安全或参数错误
        """
        try:
            executor = ensure_executor(config)

            try:
                search_path = await executor.resolve_path(path)
            except ValueError as e:
                raise ToolError(
                    message=f"Invalid path: {path} - {e}",
                    user_hint=f"The path '{path}' is invalid or outside the workspace.",
                ) from e

            search_path_obj = Path(search_path)
            disabled_roots = get_disabled_skill_roots(config)

            if disabled_roots and is_under_disabled_skill_root(str(search_path_obj), disabled_roots):
                raise ToolError(
                    message=f"Path blocked: {path}",
                    user_hint="This path belongs to a disabled skill and cannot be searched.",
                )

            # 验证路径存在且为目录
            if not search_path_obj.exists():
                suggestions = suggest_similar_paths(search_path)
                raise ToolError(
                    message=f"Path not found: {path}",
                    user_hint=format_path_not_found_hint(path, suggestions),
                )

            if not search_path_obj.is_dir():
                raise ToolError(
                    message=f"Not a directory: {path}",
                    user_hint=f"The path '{path}' is not a directory. glob_tool only searches directories.",
                )

            if io_cfg.enable_audit_log:
                logger.info(
                    f"SECURITY AUDIT: glob_tool - pattern={pattern}, path={path}, include_ignored={include_ignored}"
                )

            import asyncio

            from myrm_agent_harness.agent.meta_tools.file_search.grep_tool import _has_ripgrep

            files: list[Path] = []
            used_ripgrep = False

            if _has_ripgrep():
                try:
                    cmd = ["rg", "--files", "--color=never", "--hidden"]
                    if include_ignored:
                        cmd.append("--no-ignore")
                    cmd.extend(["--glob", pattern])
                    cmd.append("--")
                    cmd.append(str(search_path_obj))

                    proc = await asyncio.create_subprocess_exec(
                        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
                    )

                    stderr_data = bytearray()

                    async def _read_stderr():
                        while True:
                            chunk = await proc.stderr.read(4096)
                            if not chunk:
                                break
                            stderr_data.extend(chunk)

                    async def _read_lines():
                        while True:
                            line = await proc.stdout.readline()
                            if not line:
                                break
                            files.append(Path(line.decode("utf-8", errors="replace").strip()))
                            if len(files) >= io_cfg.max_search_results:
                                with contextlib.suppress(ProcessLookupError):
                                    proc.terminate()
                                break
                        await proc.wait()

                    await asyncio.wait_for(
                        asyncio.gather(_read_lines(), _read_stderr()), timeout=io_cfg.search_timeout_seconds
                    )

                    # Ignore non-zero exit codes if we terminated it early
                    if proc.returncode not in (0, 1, -15, 143) and len(files) < io_cfg.max_search_results:
                        logger.warning(f"ripgrep files search failed: {stderr_data.decode('utf-8', errors='replace')}")

                    used_ripgrep = True
                except (TimeoutError, Exception) as e:
                    logger.warning(f"ripgrep files search error: {e}, falling back to rglob")
                    with contextlib.suppress(ProcessLookupError, AttributeError):
                        proc.terminate()

            if not used_ripgrep:
                # Fallback to Python discovery with bounded candidate scan.
                try:
                    if "\x00" in pattern:
                        raise ValueError("NUL byte is not allowed in glob patterns")
                    _ = Path("validation.txt").match(pattern)
                    files = await asyncio.to_thread(
                        collect_candidate_files,
                        search_root=search_path_obj,
                        file_pattern=pattern,
                        max_files=io_cfg.max_search_results,
                        include_hidden=True,
                        include_ignored=include_ignored,
                    )

                except (ValueError, OSError) as e:
                    # 无效的 pattern（如包含非法字符）
                    raise ToolError(
                        message=f"Invalid pattern '{pattern}': {e}",
                        user_hint=f"The glob pattern '{pattern}' is invalid. Use patterns like '*.py', '**/*.js', etc.",
                    ) from e

            result_limited = len(files) >= io_cfg.max_search_results
            if result_limited:
                logger.warning(f"Glob search hit limit ({io_cfg.max_search_results}), results may be incomplete")

            if disabled_roots:
                files = [f for f in files if not is_under_disabled_skill_root(str(f), disabled_roots)]

            # 搜索无结果不是错误，返回友好的消息
            if not files:
                return f"No files found matching: {pattern}"

            # 格式化输出
            result = f"Found {len(files)} file(s) matching '{pattern}':\n\n"
            for f in sorted(files):
                # 显示相对路径
                try:
                    rel_path = f.relative_to(search_path_obj)
                    result += f" {rel_path}\n"
                except ValueError:
                    result += f" {f}\n"

            if result_limited:
                result += f"\n... (限制显示前 {io_cfg.max_search_results} 个结果)"

            return result

        except ToolError:
            # ToolError 已经包含友好提示，直接传播
            raise
        except Exception as e:
            # 未预期的错误，包装成 ToolError
            logger.exception(f"Unexpected error in glob_tool: {e}")
            raise ToolError(
                message=f"Unexpected error during file search: {e}",
                user_hint="An unexpected error occurred. Please check the search path and pattern, then try again.",
            ) from e

    return glob_func
