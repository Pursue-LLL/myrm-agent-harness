"""结果格式化器

负责格式化文件操作的输出结果。

[INPUT]
- (none)

[OUTPUT]
- FileContent: class — File Content
- DirectoryListing: class — Directory Listing
- ResultFormatter: class — Result Formatter

[POS]
Provides FileContent, DirectoryListing, ResultFormatter.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..constants import LINE_NUMBER_WIDTH, SEPARATOR_WIDTH
from .operation_context import ViewRange

# 类型别名
type DirectoryEntry = tuple[str, bool, int]  # (name, is_dir, size)


@dataclass
class FileContent:
    """文件内容数据"""

    path: str  # 文件路径
    display_path: str  # 显示路径（可能是短 ID）
    lines: list[str]  # 文件行列表
    view_range: ViewRange | None = None  # 视图范围


@dataclass
class DirectoryListing:
    """目录列表数据"""

    path: str  # 目录路径
    display_path: str  # 显示路径
    entries: list[DirectoryEntry]  # 目录条目列表


class ResultFormatter:
    """结果格式化器

    提供统一的格式化输出方法。
    """

    @staticmethod
    def _is_skill_instruction_document(path: str) -> bool:
        """判断是否是技能指令文档（SOP）

        技能指令文档需要被模型遵循，不应该被 tool_output 标签包裹。

        Args:
            path: 文件路径

        Returns:
            是否是技能指令文档
        """
        # MCP 虚拟路径：/mcp/{skill_name}/{function_name}.md
        if path.startswith("/mcp/"):
            return True

        # 技能文档：.claude/skills/*/SKILL.md 或 skills/*/SKILL.md
        return bool("SKILL.md" in path and ("/.claude/skills/" in path or "/skills/" in path))

    @staticmethod
    def format_file_content(content: FileContent) -> str:
        """格式化文件内容

        技能指令文档（SOP）：不加标签，让模型遵循
        普通文件：使用 <tool_output> 标签包裹，防止 prompt injection

        Args:
            content: 文件内容数据

        Returns:
            格式化后的字符串
        """
        total_lines = len(content.lines)

        if content.view_range:
            start_idx, end_idx = content.view_range.to_slice(total_lines)
            selected_lines = content.lines[start_idx:end_idx]

            # 添加行号
            numbered_lines = [
                f"{i + start_idx + 1:{LINE_NUMBER_WIDTH}}|{line}" for i, line in enumerate(selected_lines)
            ]
            result_content = "\n".join(numbered_lines)

            formatted = f" {content.display_path} (lines {start_idx + 1}-{end_idx} of {total_lines}):\n{result_content}"
        else:
            # 添加行号
            numbered_lines = [f"{i + 1:{LINE_NUMBER_WIDTH}}|{line}" for i, line in enumerate(content.lines)]
            result_content = "\n".join(numbered_lines)

            formatted = f" {content.display_path} ({total_lines} lines):\n{result_content}"

        # 判断是否是技能指令文档
        if ResultFormatter._is_skill_instruction_document(content.path):
            # 技能文档（SOP）：不加标签，让模型遵循
            return formatted
        else:
            # 普通文件：包裹 tool_output 标签（防止 prompt injection）
            from myrm_agent_harness.utils.context_format import wrap_with_tool_output_tag

            return wrap_with_tool_output_tag(formatted)

    @staticmethod
    def format_directory_listing(listing: DirectoryListing) -> str:
        """格式化目录列表

        使用 <tool_output> 标签包裹，防止 prompt injection。

        Args:
            listing: 目录列表数据

        Returns:
            格式化后的字符串
        """
        from myrm_agent_harness.utils.context_format import wrap_with_tool_output_tag

        result_lines: list[str] = [f" {listing.display_path}:"]

        for name, is_dir, size in listing.entries:
            if is_dir:
                result_lines.append(f" {name}/")
            else:
                result_lines.append(f" {name} ({ResultFormatter._format_size(size)})")

        formatted = "\n".join(result_lines)

        # 包裹 tool_output 标签（防止 prompt injection）
        return wrap_with_tool_output_tag(formatted)

    @staticmethod
    def format_multiple_results(results: list[str]) -> str:
        """格式化多个结果

        Args:
            results: 结果列表

        Returns:
            合并后的字符串
        """
        if len(results) == 1:
            return results[0]

        separator = "\n\n" + "=" * SEPARATOR_WIDTH + "\n\n"
        return separator.join(results)

    @staticmethod
    def format_success(operation: str, path: str) -> str:
        """格式化成功消息

        Args:
            operation: 操作名称
            path: 文件路径

        Returns:
            成功消息
        """
        return f" Successfully {operation} file: {path}"

    @staticmethod
    def _format_size(size: int) -> str:
        """格式化文件大小

        Args:
            size: 字节数

        Returns:
            格式化后的大小字符串
        """
        if size < 1024:
            return f"{size}B"
        elif size < 1024 * 1024:
            return f"{size / 1024:.1f}KB"
        else:
            return f"{size / (1024 * 1024):.1f}MB"
