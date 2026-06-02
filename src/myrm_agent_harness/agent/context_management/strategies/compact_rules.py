"""工具压缩规则定义

[INPUT]

[OUTPUT]
- CompactRule: 工具压缩规则数据类
- COMPACT_RULES: 各工具的压缩规则字典

[POS]
Tool-specific compaction rules. Defines per-tool compression strategies in a line-based format for easy grep/head/sed inspection.

"""

from dataclasses import dataclass
from typing import Literal


@dataclass
class CompactRule:
    """工具压缩规则

    Attributes:
        keep_args: 需要保留的参数名列表
        identifier_arg: 用作唯一标识符的参数名
        identifier_type: 标识符类型
        result_template: 压缩后的结果模板（支持 {identifier} 占位符）
        stats_template: 包含统计信息的增强模板（可选，支持 {identifier}, {exit_code}, {lines}, {chars} 等占位符）
    """

    keep_args: list[str]
    identifier_arg: str
    identifier_type: Literal["file_path", "url", "query", "code", "other"]
    result_template: str
    stats_template: str | None = None


COMPACT_RULES: dict[str, CompactRule] = {
    "web_search_tool": CompactRule(
        keep_args=["questions"],
        identifier_arg="questions",
        identifier_type="query",
        result_template="COMPACTED: web_search_tool\nQUERY: {identifier}",
        stats_template="COMPACTED: web_search_tool\nQUERY: {identifier}\nRESULT: {lines} lines, {chars} chars",
    ),
    "web_fetch_tool": CompactRule(
        keep_args=["url"],
        identifier_arg="url",
        identifier_type="url",
        result_template="COMPACTED: web_fetch_tool\nURL: {identifier}",
        stats_template="COMPACTED: web_fetch_tool\nURL: {identifier}\nRESULT: {lines} lines, {chars} chars",
    ),
    "bash_code_execute_tool": CompactRule(
        keep_args=["command"],
        identifier_arg="command",
        identifier_type="code",
        result_template="COMPACTED: bash_code_execute_tool\nCOMMAND: {identifier}",
        stats_template="COMPACTED: bash_code_execute_tool\nCMD: {identifier}\nEXIT: {exit_code}\nOUT: {lines} lines, {chars} chars",
    ),
    "file_read_tool": CompactRule(
        keep_args=["paths"],
        identifier_arg="paths",
        identifier_type="file_path",
        result_template="COMPACTED: file_read_tool\nPATHS: {identifier}",
        stats_template="COMPACTED: file_read_tool\nPATHS: {identifier}\nRESULT: {lines} lines, {chars} chars",
    ),
    "file_write_tool": CompactRule(
        keep_args=["path"],
        identifier_arg="path",
        identifier_type="file_path",
        result_template="COMPACTED: file_write_tool\nPATH: {identifier}",
        stats_template="COMPACTED: file_write_tool\nPATH: {identifier}\nRESULT: written {chars} chars",
    ),
    "file_edit_tool": CompactRule(
        keep_args=["path"],
        identifier_arg="path",
        identifier_type="file_path",
        result_template="COMPACTED: file_edit_tool\nPATH: {identifier}",
        stats_template="COMPACTED: file_edit_tool\nPATH: {identifier}\nRESULT: modified {chars} chars",
    ),
    "skill_select_tool": CompactRule(
        keep_args=["skill_name"],
        identifier_arg="skill_name",
        identifier_type="other",
        result_template="COMPACTED: skill_select_tool\nSKILL: {identifier}",
        stats_template="COMPACTED: skill_select_tool\nSKILL: {identifier}\nRESULT: {chars} chars",
    ),
}
