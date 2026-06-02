"""文件处理工具

提供文件操作相关的工具函数。

[INPUT]
- (none)

[OUTPUT]
- parse_path_with_range: Args:

[POS]
Provides parse_path_with_range.
"""

from __future__ import annotations

from ..constants import PATH_RANGE_PATTERN
from ..core.operation_context import ViewRange
from .path_utils import resolve_file_id_path


def parse_path_with_range(path_str: str) -> tuple[str, ViewRange | None]:
    """解析路径字符串，提取行号范围

    支持文件 ID 格式：@file_001:1-50

    Args:
        path_str: 路径字符串，如 "file.py" 或 "file.py:1-50" 或 "@file_001:1-50"

    Returns:
        (文件路径, 行号范围) 元组
    """
    match = PATH_RANGE_PATTERN.match(path_str)
    if match:
        file_path = match.group(1)
        start = int(match.group(2))
        end_str = match.group(3)
        end = int(end_str) if end_str else -1  # 空字符串表示到文件末尾

        # 解析文件 ID
        file_path = resolve_file_id_path(file_path)
        return file_path, ViewRange(start=start, end=end)

    # 没有行号范围，直接解析文件 ID
    resolved_path = resolve_file_id_path(path_str)
    return resolved_path, None
