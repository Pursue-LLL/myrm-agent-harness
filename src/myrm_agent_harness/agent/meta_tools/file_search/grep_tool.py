"""内容搜索工具（Claude Code 兼容）

[INPUT]
- langchain.tools::tool (POS: LangChain 工具装饰器)
- pydantic::BaseModel, Field (POS: 参数验证)
- agent.config.file_io::FileIOConfig (POS: I/O 配置)
- agent.security.redact::redact_sensitive_text (POS: 工具输出脱敏，防止凭证泄露到 LLM 上下文)
- regex_validator::RegexValidator (POS: 正则表达式验证器，防止 ReDoS)
- utils.lru_cache::LRUCache (POS: LRU 缓存)
- _formatter (POS: Grep flat path:line output formatter with line truncation)
- fallback_discovery::collect_candidate_files (POS: 无 ripgrep 时的候选文件发现与 git-aware ignore 策略)

[OUTPUT]
- GrepInput: Grep 工具输入参数模型
- create_grep_tool: 创建 Grep 工具的工厂函数

[POS]
Content search tool (Claude Code compatible). Searches file contents for matching text patterns
with regex and literal (--fixed-strings) modes, flat path:line output, intelligent line truncation,
and three-tier performance optimization (ripgrep > mmap+concurrency > pure Python).

"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import mmap
import re
import subprocess
import time
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

from langchain.tools import tool
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field

from myrm_agent_harness.agent.config import DEFAULT_FILE_IO_CONFIG, FileIOConfig
from myrm_agent_harness.agent.security.redact import redact_sensitive_text
from myrm_agent_harness.toolkits.code_execution.executors.base import require_executor
from myrm_agent_harness.utils.errors import ToolError

from ._formatter import format_grep_results
from .fallback_discovery import collect_candidate_files
from .path_hint import format_path_not_found_hint, suggest_similar_paths
from .regex_validator import RegexValidator
from .skill_path_filter import get_disabled_skill_roots, is_under_disabled_skill_root

if TYPE_CHECKING:
    from langchain_core.tools import BaseTool

logger = logging.getLogger(__name__)


#  性能优化：ripgrep 检测（只检测一次）
@lru_cache(maxsize=1)
def _has_ripgrep() -> bool:
    """检测系统是否有 ripgrep"""
    try:
        result = subprocess.run(["rg", "--version"], capture_output=True, timeout=1)
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


async def _ripgrep_search(
    pattern: str,
    search_path: Path,
    file_pattern: str,
    ignore_case: bool,
    context_lines: int,
    max_results: int,
    timeout_seconds: float = 10.0,
    *,
    literal: bool = False,
) -> list[dict[str, str | int]]:
    """Execute search using ripgrep (fastest tier). Returns raw match list."""
    cmd = ["rg", "--json"]

    if literal:
        cmd.append("--fixed-strings")

    if ignore_case:
        cmd.append("--ignore-case")

    if context_lines > 0:
        cmd.extend(["-C", str(context_lines)])

    if file_pattern != "**/*":
        cmd.extend(["--glob", file_pattern])

    cmd.extend(["--", pattern, str(search_path)])

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )

        results: list[dict[str, str | int]] = []
        match_count = 0
        stderr_data = bytearray()

        async def _read_stderr():
            while True:
                chunk = await proc.stderr.read(4096)
                if not chunk:
                    break
                stderr_data.extend(chunk)

        async def _read_lines():
            nonlocal match_count
            while True:
                line_bytes = await proc.stdout.readline()
                if not line_bytes:
                    break

                try:
                    line_str = line_bytes.decode("utf-8").strip()
                    if not line_str:
                        continue
                    data = json.loads(line_str)

                    if data.get("type") in ("match", "context"):
                        path_text = data["data"]["path"]["text"]
                        line_num = data["data"]["line_number"]
                        content = data["data"]["lines"]["text"].rstrip("\n")
                        line_type = data["type"]

                        results.append({
                            "file": path_text,
                            "line": line_num,
                            "content": content,
                            "type": line_type
                        })

                        if line_type == "match":
                            match_count += 1
                            if match_count >= max_results:
                                with contextlib.suppress(ProcessLookupError):
                                    proc.terminate()
                                break
                except (json.JSONDecodeError, KeyError):
                    continue
            await proc.wait()

        await asyncio.wait_for(asyncio.gather(_read_lines(), _read_stderr()), timeout=timeout_seconds)

        if proc.returncode not in (0, 1, -15, 143) and match_count < max_results:
            logger.warning(f"ripgrep error: {stderr_data.decode('utf-8', errors='replace')}")
            raise RuntimeError("ripgrep failed")

        return results

    except (TimeoutError, RuntimeError) as e:
        logger.warning(f"ripgrep search failed: {e}, falling back to Python")
        with contextlib.suppress(ProcessLookupError, AttributeError):
            proc.terminate()
        raise


def _mmap_search_file(file: Path, regex, max_matches: int = 50) -> list[dict]:
    """使用 mmap 搜索单个文件（内存高效）"""
    results = []
    try:
        with open(file, "rb") as f:
            # 空文件直接跳过
            if f.seek(0, 2) == 0:
                return results
            f.seek(0)

            # 使用 mmap（内存映射，不加载整个文件）
            with mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as mm:
                # 逐行扫描（mmap 支持迭代）
                line_num = 0
                for line_bytes in iter(mm.readline, b""):
                    line_num += 1
                    try:
                        line = line_bytes.decode("utf-8").rstrip()
                        if regex.search(line):
                            results.append({"line": line_num, "content": line})
                            if len(results) >= max_matches:
                                break
                    except UnicodeDecodeError:
                        continue

    except (OSError, ValueError):
        # mmap 失败（如空文件、权限问题），fallback 到普通读取
        pass

    return results


class GrepInput(BaseModel):
    """Grep 工具输入参数"""

    pattern: str = Field(description="搜索模式（支持正则表达式）")
    path: str = Field(default=".", description="搜索路径（默认当前目录）")
    file_pattern: str = Field(default="**/*", description="文件匹配模式（默认所有文件）")
    ignore_case: bool = Field(default=False, description="是否忽略大小写（默认 False）")
    literal: bool = Field(
        default=False,
        description="精确匹配模式：当 pattern 包含特殊字符（如 .()[]{}$^|*+?\\）时使用，跳过正则解析直接匹配文本",
    )
    context_lines: int = Field(default=0, ge=0, le=10, description="匹配行前后的上下文行数（默认 0，最大 10）")


def create_grep_tool(io_config: FileIOConfig | None = None) -> BaseTool:
    """创建内容搜索工具

    从 context 动态获取 executor 进行路径解析。
    """
    io_cfg = io_config or DEFAULT_FILE_IO_CONFIG
    regex_validator = RegexValidator(io_cfg)

    tool_description = f"""搜索文件内容。Output: one line per match as 'path:line_number: content'.

参数：
- pattern: 搜索模式（必需）
- path: 搜索路径（默认当前目录）
- file_pattern: 文件匹配模式（默认 **/*）
- ignore_case: 忽略大小写（默认 False）
- literal: 精确文本匹配（默认 False）。当 pattern 包含 .()[]{{}}$^|*+?\\ 等特殊字符时使用，无需转义

示例：
- 查找函数定义：grep_tool(pattern="def main")
- 精确匹配含特殊字符的文本：grep_tool(pattern="response.json()", literal=True)
- 正则搜索：grep_tool(pattern="class \\w+\\(.*\\):")
- 在 Python 文件中查找：grep_tool(pattern="TODO", file_pattern="**/*.py")

限制：最多 {io_cfg.max_search_results} 个结果，{io_cfg.max_search_files} 个文件，超时 {int(io_cfg.search_timeout_seconds)}s
"""

    @tool("grep_tool", description=tool_description, args_schema=GrepInput)
    async def grep_func(
        pattern: str,
        path: str = ".",
        file_pattern: str = "**/*",
        ignore_case: bool = False,
        literal: bool = False,
        context_lines: int = 0,
        *,
        config: RunnableConfig,  #  纯净设计：从 config 获取 context
    ) -> str:
        """搜索文件内容

        Args:
            pattern: 搜索模式（支持正则表达式，或 literal=True 时为精确文本）
            path: 搜索路径
            file_pattern: 文件匹配模式
            ignore_case: 是否忽略大小写
            literal: 精确文本匹配模式（跳过正则解析）
            context_lines: 匹配行前后的上下文行数
            config: LangChain 运行时配置（自动注入）

        Returns:
            匹配的行及其位置

        Raises:
            FileNotFoundError: 搜索路径不存在
            PermissionError: 权限不足
            ValueError: 路径不安全或参数错误
            ToolError: 正则表达式错误或安全问题
        """
        try:
            executor = require_executor()

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

            # 验证路径存在
            if not search_path_obj.exists():
                suggestions = suggest_similar_paths(search_path)
                raise ToolError(
                    message=f"Path not found: {path}",
                    user_hint=format_path_not_found_hint(path, suggestions),
                )

            if not pattern.strip():
                raise ToolError(
                    message="Empty search pattern",
                    user_hint="Please provide a non-empty search pattern.",
                )

            flags = re.IGNORECASE if ignore_case else 0
            if literal:
                regex = re.compile(re.escape(pattern), flags)
            else:
                regex = regex_validator.validate_and_compile(pattern, flags)

            if io_cfg.enable_audit_log:
                logger.info(
                    f"SECURITY AUDIT: grep_tool - pattern={pattern}, path={path}, "
                    f"file_pattern={file_pattern}, ignore_case={ignore_case}, literal={literal}"
                )

            # --- Search phase: collect raw results from ripgrep or Python fallback ---
            results: list[dict[str, str | int]] = []
            files_searched = 0
            used_ripgrep = False

            if _has_ripgrep():
                try:
                    results = await _ripgrep_search(
                        pattern,
                        search_path_obj,
                        file_pattern,
                        ignore_case,
                        context_lines,
                        io_cfg.max_search_results,
                        io_cfg.search_timeout_seconds,
                        literal=literal,
                    )
                    used_ripgrep = True
                except Exception as e:
                    logger.debug(f"ripgrep fallback: {e}")

            if not used_ripgrep:
                try:
                    if "\x00" in file_pattern:
                        raise ValueError("NUL byte is not allowed in file patterns")
                    _ = Path("validation.txt").match(file_pattern)
                    files = await asyncio.to_thread(
                        collect_candidate_files,
                        search_root=search_path_obj,
                        file_pattern=file_pattern,
                        max_files=io_cfg.max_search_files,
                        include_hidden=False,
                        include_ignored=False,
                    )
                except (ValueError, OSError) as e:
                    raise ToolError(
                        message=f"Invalid file pattern '{file_pattern}': {e}",
                        user_hint=f"The file pattern '{file_pattern}' is invalid. Use patterns like '*.py', '**/*.js', etc.",
                    ) from e

                files = [f for f in files if f.is_file()]

                start_time = time.time()

                async def search_file(file: Path) -> list[dict[str, str | int]]:
                    file_results: list[dict[str, str | int]] = []
                    try:
                        if file.suffix in {
                            ".pyc",
                            ".so",
                            ".dll",
                            ".exe",
                            ".bin",
                            ".jpg",
                            ".png",
                            ".gif",
                            ".pdf",
                            ".zip",
                        }:
                            return file_results

                        try:
                            file_matches = await asyncio.to_thread(
                                _mmap_search_file, file, regex, io_cfg.max_search_results
                            )
                            try:
                                rel_path = file.relative_to(search_path_obj)
                            except ValueError:
                                rel_path = file
                            for match in file_matches:
                                file_results.append(
                                    {"file": str(rel_path), "line": match["line"], "content": match["content"]}
                                )
                        except Exception:
                            content = await asyncio.to_thread(file.read_text, encoding="utf-8")
                            for line_num, line in enumerate(content.splitlines(), 1):
                                try:
                                    if regex_validator.safe_search(regex, line):
                                        try:
                                            rel_path = file.relative_to(search_path_obj)
                                        except ValueError:
                                            rel_path = file
                                        file_results.append(
                                            {"file": str(rel_path), "line": line_num, "content": line.rstrip()}
                                        )
                                        if len(file_results) >= io_cfg.max_search_results:
                                            break
                                except ToolError:
                                    break
                    except (UnicodeDecodeError, PermissionError, OSError):
                        pass
                    return file_results

                batch_size = 20
                i = 0
                batch: list[Path] = []
                for i in range(0, len(files), batch_size):
                    elapsed = time.time() - start_time
                    if elapsed > io_cfg.search_timeout_seconds:
                        logger.warning(f"Search timeout after {elapsed:.1f}s")
                        break
                    batch = files[i : i + batch_size]
                    batch_results = await asyncio.gather(*[search_file(f) for f in batch])
                    for file_results in batch_results:
                        results.extend(file_results)
                        if len(results) >= io_cfg.max_search_results:
                            break
                    if len(results) >= io_cfg.max_search_results:
                        break
                files_searched = min(i + len(batch), len(files))

            # --- Format phase ---
            if disabled_roots and results:
                filtered_results: list[dict[str, str | int]] = []
                for match in results:
                    rel_file = str(match.get("file", ""))
                    abs_file = str(search_path_obj / rel_file) if rel_file else str(search_path_obj)
                    if not is_under_disabled_skill_root(abs_file, disabled_roots):
                        filtered_results.append(match)
                results = filtered_results

            if used_ripgrep:
                files_searched = len({str(r["file"]) for r in results})

            output = format_grep_results(
                results,
                pattern,
                files_searched,
                io_cfg.max_search_results,
                is_regex=not literal,
            )

            output = redact_sensitive_text(output)

            return output

        except ToolError:
            # ToolError 已经包含友好提示，直接传播
            raise
        except Exception as e:
            # 未预期的错误，包装成 ToolError
            logger.exception(f"Unexpected error in grep_tool: {e}")
            raise ToolError(
                message=f"Unexpected error during content search: {e}",
                user_hint="An unexpected error occurred. Please check the search parameters and try again.",
            ) from e

    return grep_func
