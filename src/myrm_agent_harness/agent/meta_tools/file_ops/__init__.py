"""File operations tool module (Claude Code compatible).

提供文件查看、写入、编辑能力。

架构特性：
- core/: 核心业务逻辑（FileOperationService、OperationContext、ResultFormatter）
- strategies/: 文件系统策略（Local、WorkspaceFS、MCP）
- validators/: 验证器责任链（Path、Size、Permission）
- observers/: 观察者模式（Artifact、Tracker）
- utils/: 工具函数（路径处理、文件工具）

工具列表：
- file_read_tool: 读取文件（支持批量、MCP、File ID）
- file_write_tool: 创建/覆盖文件（自动注册 Artifact）
- file_edit_tool: 精确编辑文件（防止多重匹配）
"""

from .file_edit_tool import create_file_edit_tool
from .file_read_tool import create_file_read_tool
from .file_write_tool import create_file_write_tool

__all__ = [
    "create_file_edit_tool",
    "create_file_read_tool",
    "create_file_write_tool",
]
