"""路径验证器

验证路径的安全性，防止路径遍历攻击、符号链接攻击等。

[INPUT]
- agent.config::DEFAULT_FILE_IO_CONFIG, (POS: Configuration and type definitions for the Deep Research system. Pure data structures with no business logic dependencies.)

[OUTPUT]
- PathValidator: class — Path Validator

[POS]
Provides PathValidator.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import unquote

from myrm_agent_harness.agent.config import DEFAULT_FILE_IO_CONFIG, FileIOConfig
from myrm_agent_harness.agent.security.path_security import is_dangerous_path

from .base import Validator

if TYPE_CHECKING:
    from ..core.operation_context import OperationContext

logger = logging.getLogger(__name__)


class PathValidator(Validator):
    """路径验证器

    验证路径的安全性，防止：
    1. 路径遍历攻击（../ 和编码绕过）
    2. 符号链接攻击
    3. 访问危险系统路径
    4. 路径深度攻击
    """

    def __init__(self, allowed_base_paths: list[str] | None = None, io_config: FileIOConfig | None = None) -> None:
        """初始化验证器

        Args:
            allowed_base_paths: 允许的基础路径列表（可选）
            io_config: I/O 配置（可选，默认使用全局配置）
        """
        super().__init__()
        self.allowed_base_paths = [os.path.abspath(p) for p in (allowed_base_paths or [])]
        self.io_config = io_config or DEFAULT_FILE_IO_CONFIG

    async def _do_validate(self, context: OperationContext, path: str) -> None:
        """验证路径安全性"""
        # MCP 虚拟路径跳过验证
        if path.startswith("/mcp/"):
            return

        # 解码 URL 编码（防止编码绕过，如 %2e%2e）
        decoded_path = unquote(path)

        # 检查路径遍历攻击
        self._check_path_traversal(decoded_path)

        # 规范化路径（解析 .. 和 . 等）
        normalized_path = os.path.normpath(decoded_path)

        # 获取绝对路径
        try:
            abs_path = os.path.abspath(normalized_path)
        except (OSError, ValueError) as e:
            raise ValueError(f"Invalid path format: {path}") from e

        # 检查路径深度
        self._check_path_depth(abs_path)

        # 检查符号链接
        if not self.io_config.follow_symlinks:
            self._check_symlink(abs_path)

        # 检查是否在允许的基础路径内
        if self.allowed_base_paths:
            self._check_allowed_base_paths(abs_path, path)

        # 检查危险路径
        self._check_dangerous_paths(abs_path, decoded_path)

        # 审计日志
        if self.io_config.enable_audit_log:
            self._audit_log(path, abs_path, context)

    def _check_path_traversal(self, path: str) -> None:
        """检查路径遍历攻击

        Args:
            path: 解码后的路径

        Raises:
            PermissionError: 检测到路径遍历攻击
        """
        # 检查路径遍历模式（路径已经 URL 解码，只需检查实际模式）
        traversal_patterns = [
            "..",  # Standard traversal
            "/..",  # Unix path traversal
            "..\\",  # Windows path traversal
        ]

        for pattern in traversal_patterns:
            if pattern in path:
                raise PermissionError(
                    f"Path traversal attack detected: {path}. Relative paths with '..' are not allowed."
                )

    def _check_path_depth(self, abs_path: str) -> None:
        """检查路径深度

        Args:
            abs_path: 绝对路径

        Raises:
            ValueError: 路径深度超过限制
        """
        path_parts = Path(abs_path).parts
        if len(path_parts) > self.io_config.max_path_depth:
            raise ValueError(f"Path depth exceeds maximum allowed ({self.io_config.max_path_depth}): {abs_path}")

    def _check_symlink(self, abs_path: str) -> None:
        """检查符号链接

        Args:
            abs_path: 绝对路径

        Raises:
            PermissionError: 路径包含符号链接
        """
        path_obj = Path(abs_path)

        # 检查路径本身是否是符号链接
        if path_obj.exists() and path_obj.is_symlink():
            raise PermissionError(f"Symbolic links are not allowed for security reasons: {abs_path}")

        # 检查父目录链中是否包含符号链接
        try:
            # 逐级检查父目录
            for parent in path_obj.parents:
                if parent.exists() and parent.is_symlink():
                    raise PermissionError(
                        f"Path contains symbolic link in parent directory: {abs_path}\n"
                        f"Symlink found at: {parent}\n"
                        f"Hint: Use a workspace-relative path instead of absolute paths "
                        f"with symlinks (e.g., write to 'script.py' instead of '{abs_path}')."
                    )

            # 使用 resolve() 检测路径中的符号链接
            # 如果路径中包含符号链接，resolve() 后的路径会不同
            try:
                resolved = path_obj.resolve(strict=False)
                # 将两者都转为绝对路径再比较
                # 如果两个路径都存在但 resolve 后不同，说明有符号链接
                if resolved.exists() and path_obj.exists() and str(resolved.absolute()) != str(path_obj.absolute()):
                    raise PermissionError(f"Path contains symbolic link: {abs_path}\nResolves to: {resolved}")
            except (OSError, RuntimeError) as e:
                # 可能是循环符号链接
                raise PermissionError(f"Invalid path (possible symlink loop): {abs_path}") from e

        except PermissionError:
            # 重新抛出权限错误
            raise
        except Exception as e:
            # 其他异常，记录日志但不阻止操作
            logger.warning(f"Failed to check symlinks for {abs_path}: {e}")

    def _check_allowed_base_paths(self, abs_path: str, original_path: str) -> None:
        """检查路径是否在允许的基础路径内

        Args:
            abs_path: 绝对路径
            original_path: 原始路径

        Raises:
            PermissionError: 路径不在允许的基础路径内
        """
        # 使用 os.path.commonpath 进行严格的路径前缀检查
        is_allowed = False
        for base in self.allowed_base_paths:
            try:
                # 使用 commonpath 确保真正的父子关系
                common = os.path.commonpath([abs_path, base])
                if common == base:
                    is_allowed = True
                    break
            except ValueError:
                # 不同驱动器（Windows）或路径格式不兼容
                continue

        if not is_allowed:
            raise PermissionError(
                f"Access denied: Path outside allowed directories: {original_path}\n"
                f"Allowed base paths: {', '.join(self.allowed_base_paths)}"
            )

    def _check_dangerous_paths(self, abs_path: str, decoded_path: str) -> None:
        """检查危险路径

        Args:
            abs_path: 绝对路径
            decoded_path: 解码后的原始路径

        Raises:
            PermissionError: 路径匹配危险路径模式
        """
        if is_dangerous_path(abs_path):
            raise PermissionError(f"Access to dangerous path is forbidden: {decoded_path}")

    def _audit_log(self, original_path: str, abs_path: str, context: OperationContext) -> None:
        """记录安全审计日志

        Args:
            original_path: 原始路径
            abs_path: 绝对路径
            context: 操作上下文
        """
        logger.info(
            f"Path validation passed: operation={context.operation.value}, "
            f"original_path={original_path}, resolved_path={abs_path}"
        )
