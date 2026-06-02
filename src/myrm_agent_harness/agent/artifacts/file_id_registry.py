"""文件 ID 注册表

用于在 Agent 会话中管理大型工具结果的短 ID 映射。

设计目的：
- 大型工具结果转储到文件后，使用短 ID（如 @file_001）代替完整路径
- 节省模型在后续调用中使用的 token 数量

使用方式：
1. 使用 ArtifactContextManager 初始化上下文
2. 转储文件时注册映射
3. file_read_tool、file_write_tool、file_edit_tool 和 bash_code_execute_tool 解析短 ID

Example:
    ```python
    from myrm_agent_harness.agent.artifacts import ArtifactContextManager, get_artifact_context

    async with ArtifactContextManager():
        ctx = get_artifact_context()
        file_id = ctx.file_id_registry.register("/full/path/to/file.txt")
        # file_id = "@file_001"
    ```

[INPUT]
- (none)

[OUTPUT]
- FileIdRegistry: class — File Id Registry
- register_file: Args:
- resolve_file_id: Args:
- resolve_file_ids_in_text: Args:
- is_file_id: Args:

[POS]
Example:
"""

import logging
import re
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# 文件 ID 前缀
FILE_ID_PREFIX = "@file_"

# 文件 ID 正则表达式（匹配 @file_001, @file_002 等）
FILE_ID_PATTERN = re.compile(r"@file_(\d+)")


@dataclass
class FileIdRegistry:
    """文件 ID 注册表

    维护短 ID 到完整路径的映射关系。
    """

    # 短 ID -> 完整路径
    id_to_path: dict[str, str] = field(default_factory=dict)

    # 完整路径 -> 短 ID（反向映射，用于去重）
    path_to_id: dict[str, str] = field(default_factory=dict)

    # 下一个可用的 ID 序号
    next_id: int = 1

    def register(self, full_path: str) -> str:
        """注册文件并返回短 ID

        如果路径已注册，返回已有的 ID（去重）。

        Args:
            full_path: 文件的完整路径

        Returns:
            短 ID，如 @file_001
        """
        # 检查是否已注册
        if full_path in self.path_to_id:
            return self.path_to_id[full_path]

        # 生成新 ID
        file_id = f"{FILE_ID_PREFIX}{self.next_id:03d}"
        self.next_id += 1

        # 存储映射
        self.id_to_path[file_id] = full_path
        self.path_to_id[full_path] = file_id

        logger.info(f" 注册文件 ID: {file_id} -> {full_path}")
        return file_id

    def resolve(self, file_id: str) -> str | None:
        """解析短 ID 为完整路径

        Args:
            file_id: 短 ID，如 @file_001

        Returns:
            完整路径，如果 ID 不存在则返回 None
        """
        return self.id_to_path.get(file_id)

    def get_all_mappings(self) -> dict[str, str]:
        """获取所有映射（用于调试）"""
        return dict(self.id_to_path)


def _get_registry() -> FileIdRegistry | None:
    """获取当前的文件 ID 注册表"""
    from .context import get_artifact_context

    ctx = get_artifact_context()
    if ctx is not None:
        return ctx.file_id_registry
    return None


def register_file(full_path: str) -> str | None:
    """注册文件并返回短 ID

    便捷函数，自动获取当前注册表。

    Args:
        full_path: 文件的完整路径

    Returns:
        短 ID，如果注册表未初始化则返回 None
    """
    registry = _get_registry()
    if registry is None:
        logger.debug("文件 ID 注册表未初始化，无法注册文件")
        return None
    return registry.register(full_path)


def resolve_file_id(file_id: str) -> str | None:
    """解析短 ID 为完整路径

    便捷函数，自动获取当前注册表。

    Args:
        file_id: 短 ID，如 @file_001

    Returns:
        完整路径，如果 ID 不存在或注册表未初始化则返回 None
    """
    registry = _get_registry()
    if registry is None:
        return None
    return registry.resolve(file_id)


def resolve_file_ids_in_text(text: str) -> str:
    """替换文本中所有的文件 ID 为完整路径

    用于 bash_code_execute_tool 预处理代码。

    Args:
        text: 包含 @file_xxx 引用的文本

    Returns:
        替换后的文本
    """
    registry = _get_registry()
    if registry is None:
        return text

    replaced_ids: list[str] = []

    def replace_match(match: re.Match[str]) -> str:
        file_id = match.group(0)
        full_path = registry.resolve(file_id)
        if full_path:
            replaced_ids.append(file_id)
            return full_path
        return file_id  # 未找到则保持原样

    result = FILE_ID_PATTERN.sub(replace_match, text)

    # 如果有替换，输出日志
    if replaced_ids:
        logger.info(f" 解析文件 ID: {', '.join(replaced_ids)}")

    return result


def is_file_id(path: str) -> bool:
    """检查路径是否是文件 ID 格式

    Args:
        path: 路径字符串

    Returns:
        是否是 @file_xxx 格式
    """
    return path.startswith(FILE_ID_PREFIX)


__all__ = [
    "FILE_ID_PATTERN",
    "FILE_ID_PREFIX",
    "FileIdRegistry",
    "is_file_id",
    "register_file",
    "resolve_file_id",
    "resolve_file_ids_in_text",
]
