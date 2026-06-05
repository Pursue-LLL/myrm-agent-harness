"""增量日志读取工具（Claude Code 兼容）

[INPUT]
- langchain.tools::tool (POS: Defines the 3 fake/meta tools injected into the orchestrator LLM context. These tools are never executed by a real runtime — the orchestrator intercepts their tool_call outputs and drives the state machine transitions. dispatch_research: dispatches a research sub-run with a task description think: chain-of-thought scratchpad (non-reasoning models only) finalize_report: signals the orchestrator to transition to the report phase)
- pydantic::BaseModel, Field
- toolkits.code_execution.executors.base::get_executor (POS: Code executor base classes.)
- utils.errors::ToolError (POS: Storage quota related errors.)

[OUTPUT]
- create_incremental_read_tool(): 工厂函数
- read_incremental_log_tool: LangChain Tool

[POS]
Incremental log reader tool. Reads file content incrementally from a start_offset, preventing token explosion and cache invalidation from re-reading old logs. Provides native regex filtering.

"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
from pathlib import Path
from typing import TYPE_CHECKING

from langchain.tools import tool
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field

from myrm_agent_harness.agent.security.redact import redact_sensitive_text
from myrm_agent_harness.toolkits.code_execution.executors.base import get_executor
from myrm_agent_harness.utils.errors import ToolError

if TYPE_CHECKING:
    from langchain_core.tools import BaseTool

logger = logging.getLogger(__name__)


class IncrementalReadInput(BaseModel):
    """增量日志读取工具输入参数"""

    file_path: str = Field(description="需要增量读取的本地日志文件路径。")
    cursor: str | int = Field(
        default="0",
        description="上次读取结束时的全息游标凭证。首次读取传 '0'。必须严格使用上一次工具返回的 Next cursor 值（例如 '51200:8172391:a1b2c3d4:15'）。",
    )
    filter_pattern: str | None = Field(
        default=None,
        description="可选的正则表达式（Python 语法），用于仅保留匹配的新增行。例如 '(?i)error|warn|exception'。",
    )
    context_lines: int = Field(
        default=5, description="在使用 filter_pattern 过滤时，匹配行前后额外保留的上下文行数，便于查看完整的错误堆栈。"
    )


def _parse_cursor(cursor_str: str | int) -> tuple[int, int, str, int]:
    """解析全息游标字符串，返回 (offset, inode, head_hash, hash_len)"""
    parts = str(cursor_str).split(":")
    if len(parts) == 4:
        try:
            return int(parts[0]), int(parts[1]), parts[2], int(parts[3])
        except ValueError:
            pass
    elif len(parts) == 1 and parts[0].isdigit():
        return int(parts[0]), 0, "", 0
    return 0, 0, "", 0


def _get_file_identity(f, hash_len: int = 64) -> tuple[int, str, int]:
    """获取文件的物理特征：Inode 和指定长度头部的哈希值"""
    st = os.fstat(f.fileno())
    inode = st.st_ino

    current_pos = f.tell()
    f.seek(0, 2)
    actual_size = f.tell()

    read_len = min(hash_len, actual_size)
    f.seek(0)
    head_bytes = f.read(read_len)
    head_hash = hashlib.md5(head_bytes).hexdigest()[:8] if read_len > 0 else ""
    f.seek(current_pos)

    return inode, head_hash, read_len


def _read_and_filter_sync(
    resolved_path: Path, cursor: str | int, filter_pattern: str | None, context_lines: int
) -> str:
    """同步地增量读取文件内容、执行行边界截断、净化 ANSI、执行智能上下文正则匹配。"""

    start_offset, old_inode, old_hash, old_hash_len = _parse_cursor(cursor)

    with open(resolved_path, "rb") as f:
        # 三重防盲比对：应对包括 copytruncate 在内的所有日志轮转竞态条件
        if old_hash_len > 0:
            _, check_hash, _ = _get_file_identity(f, hash_len=old_hash_len)
        else:
            check_hash = old_hash

        current_inode, current_hash, current_hash_len = _get_file_identity(f, hash_len=64)

        f.seek(0, 2)
        actual_size = f.tell()

        rotated = False
        if old_inode != 0 and current_inode != old_inode:
            rotated = True  # Inode 改变 (mv / create 轮转)
        elif old_hash and check_hash != old_hash:
            rotated = True  # Inode 未变但头部内容篡改 (copytruncate 轮转)
        elif actual_size < start_offset:
            rotated = True  # 异常缩水兜底

        if rotated:
            logger.warning(f"Log rotation detected for {resolved_path}. Resetting offset to 0.")
            start_offset = 0

        f.seek(start_offset)

        # 动态分块读取，防止“无过滤直读”时的“游标黑洞（Silent Data Loss）”
        if filter_pattern:
            chunk_size = 2 * 1024 * 1024
        else:
            chunk_size = 50 * 1024

        new_data = f.read(chunk_size)

    if not new_data:
        return f"[No new logs found]\n\n[System] Current log read complete. To read new logs next time, use cursor={start_offset}:{current_inode}:{current_hash}:{current_hash_len}"

    # 安全行边界截断 (Newline Alignment)
    last_newline_idx = new_data.rfind(b"\n")
    if last_newline_idx != -1:
        new_data = new_data[: last_newline_idx + 1]
        next_offset = start_offset + last_newline_idx + 1
    else:
        next_offset = start_offset + len(new_data)

    next_cursor = f"{next_offset}:{current_inode}:{current_hash}:{current_hash_len}"

    text = new_data.decode("utf-8", errors="replace")
    ansi_escape = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
    text = ansi_escape.sub("", text)
    lines = text.splitlines()

    if filter_pattern:
        try:
            pattern = re.compile(filter_pattern)
            included_indices = set()
            for i, line in enumerate(lines):
                if pattern.search(line):
                    start_idx = max(0, i - context_lines)
                    end_idx = min(len(lines), i + context_lines + 1)
                    for j in range(start_idx, end_idx):
                        included_indices.add(j)

            if not included_indices:
                return f"[No lines matched the filter_pattern '{filter_pattern}']\n\n[System] Current log read complete. To read new logs next time, use cursor={next_cursor}"

            filtered_lines = []
            sorted_indices = sorted(list(included_indices))
            last_idx = -1
            for idx in sorted_indices:
                if last_idx != -1 and idx > last_idx + 1:
                    filtered_lines.append("--- [Context Gap] ---")
                filtered_lines.append(lines[idx])
                last_idx = idx

            lines = filtered_lines

            # 过滤模式下，允许截断只保留最新报错
            max_lines = 500
            if len(lines) > max_lines:
                lines = lines[-max_lines:]
                lines.insert(
                    0, f"[... earlier matched logs in this {chunk_size // 1024}KB chunk truncated for length ...]"
                )

        except re.error as e:
            return f"Invalid regex pattern '{filter_pattern}': {e}"
    else:
        # 无过滤模式下，坚决废除截断，纯依靠 50KB 物理块阻挡 OOM，实现 100% 物理无损分页
        pass

    text = "\n".join(lines)
    result = f"--- New Logs ---\n{text}\n\n[System] Current log read complete. To read new logs next time, use cursor={next_cursor}"
    return redact_sensitive_text(result)


def create_incremental_read_tool(skills: list | None = None) -> BaseTool:
    """创建增量日志读取工具"""

    @tool(
        "read_incremental_log_tool",
        description="""增量读取并监控后台日志文件。
每次只返回文件中新增的内容，完美避免重复读取旧日志导致的 Token 污染。
工具返回的末尾会提示 `Next cursor: <string>`，下次调用时必须将此完整字符串作为 cursor 参数传入！

参数：
- file_path: 日志文件路径
- cursor: 全息游标凭证（如 "51200:8172391:a1b2c3d4:15"）。第一次读传 "0"，后续严格传上次返回的 Next cursor。
- filter_pattern: (可选) 正则过滤条件，返回包含匹配字符串的行及其前后上下文（如 '(?i)error|warn'）。
- context_lines: (可选) 匹配行的前后保留多少行上下文（默认 5 行），极大便利排查跨多行的堆栈报错。

 仅支持本地文件，不能监控 /mcp/ 虚拟路径或 URL。
""",
        args_schema=IncrementalReadInput,
    )
    async def incremental_read_func(
        file_path: str,
        cursor: str | int = "0",
        filter_pattern: str | None = None,
        context_lines: int = 5,
        *,
        config: RunnableConfig,
    ) -> str:
        """增量读取并监控后台日志文件。"""
        try:
            if file_path.startswith("/mcp/") or file_path.startswith("http"):
                raise ValueError("read_incremental_log_tool only supports local files.")

            executor = get_executor()
            cwd = executor.get_workspace_path() if executor else Path.cwd()
            workspace_path = Path(file_path)

            if not workspace_path.is_absolute():
                workspace_path = cwd / workspace_path

            resolved_path = workspace_path.resolve()
            if not str(resolved_path).startswith(str(cwd.resolve())):
                raise PermissionError("Path traversal detected: Cannot read files outside workspace.")

            if not resolved_path.exists() or not resolved_path.is_file():
                raise FileNotFoundError(f"Log file not found: {file_path}")

            return await asyncio.to_thread(
                _read_and_filter_sync,
                resolved_path,
                cursor,
                filter_pattern,
                context_lines,
            )

        except ToolError:
            raise
        except FileNotFoundError as e:
            raise ToolError(message=str(e), user_hint="The log file does not exist.") from e
        except PermissionError as e:
            raise ToolError(message=str(e), user_hint="Permission denied reading this path.") from e
        except Exception as e:
            logger.exception(f"Unexpected error in read_incremental_log_tool: {e}")
            raise ToolError(message=f"Unexpected error: {e}", user_hint="An unexpected error occurred.") from e

    return incremental_read_func
