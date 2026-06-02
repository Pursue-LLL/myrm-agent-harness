"""MCPFileSystemStrategy - MCP 虚拟路径策略

读取 MCP 技能函数文档（虚拟文件系统）。

路径格式：/mcp/{skill_name}/{function_name}.md
特性：只读（不支持写入、编辑操作）

[INPUT]
- backends.skills.types::SkillMetadata (POS: Provides ArtifactInfo, infer_language, infer_artifact_type.)
- agent.skills.mcp.core_generator::MCPSkillGenerator (POS: MCP Skill Generator - MCP-to-Skill conversion with progressive disclosure.)

[OUTPUT]
- MCPFileSystemStrategy: class — M C P File System Strategy
- main: Parse execution output from the wrapper script.

[POS]
Provides MCPFileSystemStrategy, main.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .base import FileSystemStrategy

if TYPE_CHECKING:
    from myrm_agent_harness.backends.skills.types import SkillMetadata

    from ..core.operation_context import ViewRange


class MCPFileSystemStrategy(FileSystemStrategy):
    """MCP 虚拟路径策略

    读取 MCP 技能函数文档（虚拟文件系统）。

    路径格式：/mcp/{skill_name}/{function_name}.md
    示例：/mcp/12306_skill/get-tickets.md

    特性：
    - 只读（不支持 write/edit 操作）
    - 不需要 StorageProvider
    - 从技能元数据中提取函数文档
    """

    def __init__(self, skills: list[SkillMetadata]) -> None:
        """初始化策略

        Args:
            skills: MCP 技能列表（包含函数元数据）
        """
        self.skills = skills

    async def read_file(self, path: str, view_range: ViewRange | None = None) -> list[str]:
        """读取 MCP 函数文档"""
        doc = self._read_mcp_function_doc(path)
        return doc.split("\n")

    async def write_file(self, path: str, content: str) -> None:
        """MCP 路径不支持写入"""
        raise PermissionError(f"Cannot write to MCP virtual path: {path}")

    async def delete_file(self, path: str) -> None:
        """MCP 路径不支持删除"""
        raise PermissionError(f"Cannot delete MCP virtual path: {path}")

    async def replace_text(self, path: str, old_str: str, new_str: str) -> None:
        """MCP 路径不支持替换"""
        raise PermissionError(f"Cannot modify MCP virtual path: {path}")

    async def is_directory(self, path: str) -> bool:
        """检查 MCP 路径是否是目录

        /mcp/{skill_name} 被视为目录（可以列出工具）
        /mcp/{skill_name}/{function_name}.md 被视为文件
        """
        parts = path.rstrip("/").split("/")
        # /mcp/{skill_name} 是目录
        if len(parts) == 3:
            skill_name = parts[2]
            skill_meta = next((s for s in self.skills if s.name == skill_name), None)
            return skill_meta is not None and skill_meta.is_mcp_skill
        # /mcp/{skill_name}/{function_name}.md 是文件
        return False

    async def list_directory(self, path: str) -> list[tuple[str, bool, int]]:
        """列出 MCP 技能的所有工具

        返回格式：[(name, is_dir, size), ...]
        """
        parts = path.rstrip("/").split("/")
        if len(parts) != 3:
            raise NotADirectoryError(f"Invalid MCP directory path: {path}")

        skill_name = parts[2]
        skill_meta = next((s for s in self.skills if s.name == skill_name), None)

        if not skill_meta:
            raise FileNotFoundError(f"Skill not found: {skill_name}")

        if not skill_meta.is_mcp_skill:
            raise ValueError(f"'{skill_name}' is not an MCP skill")

        # 列出所有工具
        if not skill_meta.mcp:
            return []

        result = []
        for tool_name in skill_meta.mcp.tools:
            # 返回 .md 文件名
            filename = f"{tool_name}.md"
            # 估算大小（使用缓存或默认值）
            size = len(skill_meta.mcp.tool_docs.get(tool_name, "")) or 1024
            result.append((filename, False, size))

        return result

    async def exists(self, path: str) -> bool:
        """检查 MCP 路径是否存在

        支持：
        - /mcp/{skill_name} (目录)
        - /mcp/{skill_name}/{function_name}.md (文件)
        """
        parts = path.rstrip("/").split("/")

        # /mcp/{skill_name} - 检查技能是否存在
        if len(parts) == 3:
            skill_name = parts[2]
            skill_meta = next((s for s in self.skills if s.name == skill_name), None)
            return skill_meta is not None and skill_meta.is_mcp_skill

        # /mcp/{skill_name}/{function_name}.md - 检查函数文档是否存在
        try:
            self._read_mcp_function_doc(path)
            return True
        except (ValueError, FileNotFoundError):
            return False

    async def get_file_size(self, path: str) -> int:
        """获取 MCP 文档大小"""
        doc = self._read_mcp_function_doc(path)
        return len(doc.encode("utf-8"))

    def get_actual_path(self, path: str) -> str:
        """MCP 路径返回自身"""
        return path

    def _read_mcp_function_doc(self, path: str) -> str:
        """读取 MCP 函数文档

        Args:
            path: MCP 路径，格式：/mcp/{skill_name}/{function_name}

        Returns:
            函数文档

        Raises:
            ValueError: 路径格式错误
            FileNotFoundError: 技能或函数不存在
        """
        parts = path.split("/")
        if len(parts) < 4:
            raise ValueError(f"Invalid MCP path: {path} - Format: /mcp/{{skill_name}}/{{function_name}}")

        skill_name = parts[2]
        function_name = parts[3]

        # 去除 .md 后缀
        if function_name.endswith(".md"):
            function_name = function_name[:-3]

        # 查找技能
        skill_meta = next((s for s in self.skills if s.name == skill_name), None)
        if not skill_meta:
            available = [s.name for s in self.skills]
            raise FileNotFoundError(f"Skill not found: {skill_name} (available: {available})")

        # 检查是否是 MCP 技能
        if not skill_meta.is_mcp_skill:
            raise ValueError(f"'{skill_name}' is not an MCP skill")

        # 使用 MCPSkillGenerator 生成工具文档
        from myrm_agent_harness.agent.skills.mcp.core_generator import MCPSkillGenerator

        generator = MCPSkillGenerator()
        doc = generator.generate_tool_doc(skill_meta, function_name)

        return f" /mcp/{skill_name}/{function_name}.md:\n{doc}\n\n{self._get_mcp_call_rules()}"

    @staticmethod
    def _get_mcp_call_rules() -> str:
        """获取 MCP 调用规则"""
        return """

## MCP Function Call Rules

1. **Import**: `from skills.skill_name import function_name` (Do NOT use `from skills import skill_name`)
2. **Async**: Use standard async/await pattern, use async def main() + asyncio.run(main())
3. **Output Format** (only these two are allowed):
  - Intermediate observation: `print(f"[OBSERVATION] {variable}")`
  - Final result: `print(f"[RESULT] {result}")`
4. **Note**: When return value structure is unclear, use `[OBSERVATION]` first to inspect the structure.

**Example**:
```python
import asyncio
from skills.{skill_name} import function_name # skill_name replace with the actual skill name

async def main():
    result = await function_name(param1="value1", param2=123)
    print(f"[OBSERVATION] {variable}")  # Intermediate observation
    print(f"[RESULT] {result}")  # Final result

asyncio.run(main())
```
"""
