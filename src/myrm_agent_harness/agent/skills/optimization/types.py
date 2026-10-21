"""Skill Optimization Types

1. 本文件的 INPUT/OUTPUT/POS 注释

[INPUT]
- dataclasses.dataclass (POS: Python数据类装饰器)

[OUTPUT]
- SecurityValidationResult: 安全验证结果
- SecurityError: 安全验证失败异常
- SkillVersion: Skill版本记录

[POS]
Skill version history and security validation type definitions.

"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass
class SecurityValidationResult:
    """安全验证结果"""

    passed: bool
    issues: list[str]  # 安全问题列表

    @property
    def is_safe(self) -> bool:
        """是否安全"""
        return self.passed and len(self.issues) == 0


@dataclass
class SkillVersion:
    """Skill版本

    记录skill的每个版本，支持版本回滚。
    """

    skill_id: str
    version: int  # 版本号，从1开始递增
    content: str  # Skill内容
    created_at: datetime
    created_by: str  # "llm" | "manual" | "rollback"
    optimization_id: str | None = None  # 关联的优化ID（如果是LLM优化产生的）
    is_active: bool = False  # 是否为当前激活版本
    metadata: dict | None = None  # 额外元数据


class SecurityError(Exception):
    """安全验证失败异常"""

    pass
