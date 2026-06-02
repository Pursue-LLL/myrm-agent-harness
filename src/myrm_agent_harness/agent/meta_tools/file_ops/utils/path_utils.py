"""路径处理工具

提供路径解析、规范化等功能。

[INPUT]
- (none)

[OUTPUT]
- resolve_file_id_path: Args:

[POS]
Provides resolve_file_id_path.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def resolve_file_id_path(path: str) -> str:
    """解析文件 ID 为实际路径

    如果路径是 @file_xxx 格式，解析为实际路径。
    否则返回原路径。

    Args:
        path: 路径字符串，可能是 @file_001 或实际路径

    Returns:
        实际文件路径
    """
    from myrm_agent_harness.agent.artifacts.file_id_registry import is_file_id, resolve_file_id

    if is_file_id(path):
        resolved = resolve_file_id(path)
        if resolved:
            logger.info(f"Resolved file ID: {path} -> {resolved}")
            return resolved
        else:
            logger.warning(f"File ID not found: {path}")

    return path
