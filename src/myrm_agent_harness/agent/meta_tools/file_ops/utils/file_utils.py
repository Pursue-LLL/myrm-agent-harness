"""文件处理工具

提供文件操作相关的工具函数。

[INPUT]
- (none)

[OUTPUT]
- parse_path_with_range: 解析路径字符串，提取文件路径与合法正整数行号范围

[POS]
Provides parse_path_with_range with positive line numbers and ordered range validation.
"""

from __future__ import annotations

from ..constants import PATH_RANGE_PATTERN
from ..core.operation_context import ViewRange
from .path_utils import resolve_file_id_path


def parse_path_with_range(path_str: str) -> tuple[str, ViewRange | None]:
    """解析路径字符串，提取行号范围

    支持文件 ID 格式：@file_001:1-50
    支持 vault 指针：vault://uuid:1-50

    Args:
        path_str: 路径字符串，如 "file.py" 或 "file.py:1-50" 或 "@file_001:1-50"

    Returns:
        (文件路径, 行号范围) 元组

    Raises:
        ValueError: 当行号为非正整数（< 1）或结束行号小于起始行号时抛出明确异常。
    """
    match = PATH_RANGE_PATTERN.match(path_str)
    if match:
        file_path = match.group(1)
        start = int(match.group(2))
        end_str = match.group(3)
        end = int(end_str) if end_str else -1  # 空字符串表示到文件末尾

        if start < 1:
            raise ValueError(
                f"Invalid line range start in '{path_str}': start line must be a positive integer (>= 1), got {start}"
            )
        if end != -1:
            if end < 1:
                raise ValueError(
                    f"Invalid line range end in '{path_str}': end line must be a positive integer (>= 1), got {end}"
                )
            if end < start:
                raise ValueError(
                    f"Invalid line range in '{path_str}': end line ({end}) cannot be less than start line ({start})"
                )

        # 解析文件 ID
        file_path = resolve_file_id_path(file_path)
        return file_path, ViewRange(start=start, end=end)

    # 没有行号范围，直接解析文件 ID
    resolved_path = resolve_file_id_path(path_str)
    return resolved_path, None
