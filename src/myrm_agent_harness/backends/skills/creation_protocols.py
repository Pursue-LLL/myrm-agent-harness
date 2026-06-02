"""Skill write backend protocol.

[INPUT]
- typing::Protocol, runtime_checkable (POS: Python 协议类型)

[OUTPUT]
- SkillSaveResult: 保存结果数据类
- SkillDeleteResult: 删除结果数据类
- SkillResourceWriteResult: 辅助文件写入结果数据类
- SkillWriteBackend: 技能写入后端协议

[POS]
Skill write-backend protocol. Defines unified interface for creating, updating, and deleting skills and their auxiliary files.

"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class SkillSaveResult:
    """技能保存结果（不可变）"""

    success: bool
    skill_name: str = ""
    skill_id: str = ""
    saved_path: str = ""
    was_updated: bool = False
    error: str = ""
    scan_report: str = ""


@dataclass(frozen=True)
class SkillDeleteResult:
    """技能删除结果（不可变）"""

    success: bool
    skill_name: str = ""
    error: str = ""


@dataclass(frozen=True)
class SkillResourceWriteResult:
    """辅助文件写入/删除结果（不可变）"""

    success: bool
    skill_name: str = ""
    resource_path: str = ""
    error: str = ""
    scan_report: str = ""


@runtime_checkable
class SkillWriteBackend(Protocol):
    """技能写入后端协议（框架层定义，业务层实现）

    职责：
    - save_skill: 将 Agent 生成的 SKILL.md 保存到存储系统并自动注册/启用
    - delete_skill: 从存储系统删除技能并注销
    - write_resource: 写入辅助文件（scripts/references/templates/assets）
    - delete_resource: 删除辅助文件

    业务层根据部署模式（Local/Sandbox）选择不同的存储策略。
    安全扫描由框架层 ScanningSkillWriteBackend 包装类强制执行，
    业务层实现无需关心安全扫描。
    """

    async def save_skill(
        self,
        name: str,
        content: str,
        description: str = "",
    ) -> SkillSaveResult:
        """保存技能（创建或全量更新）

        将 SKILL.md 内容保存到存储系统，自动注册并启用。

        Args:
            name: 技能名称（必须符合 ^[a-zA-Z][a-zA-Z0-9_-]*$ 格式）
            content: SKILL.md 完整内容（含 YAML frontmatter）
            description: 技能描述（可选，若为空则从 content 中解析）

        Returns:
            保存结果（含技能 ID、路径等信息）
        """
        ...

    async def delete_skill(
        self,
        name: str,
    ) -> SkillDeleteResult:
        """删除技能

        从存储系统删除技能文件并注销。

        Args:
            name: 技能名称

        Returns:
            删除结果
        """
        ...

    async def write_resource(
        self,
        skill_name: str,
        resource_path: str,
        content: str,
    ) -> SkillResourceWriteResult:
        """写入辅助文件到技能目录。

        Args:
            skill_name: 技能名称
            resource_path: 相对路径（如 "scripts/analyze.py"）
            content: 文件内容（文本）

        Returns:
            写入结果
        """
        ...

    async def delete_resource(
        self,
        skill_name: str,
        resource_path: str,
    ) -> SkillResourceWriteResult:
        """删除辅助文件。

        Args:
            skill_name: 技能名称
            resource_path: 相对路径（如 "scripts/analyze.py"）

        Returns:
            删除结果
        """
        ...
