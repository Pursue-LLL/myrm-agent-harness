"""Skill discovery backend protocols.

[INPUT]
- typing::Protocol, runtime_checkable (POS: Python 协议类型)

[OUTPUT]
- SkillSearchResult: 搜索结果数据类
- SkillInstallResult: 安装结果数据类
- SkillDiscoveryBackend: 技能发现后端协议

[POS]
Skill discovery backend protocol. Defines unified interface for searching and installing external skills.

"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol, runtime_checkable


@dataclass(frozen=True)
class SkillSearchResult:
    """技能搜索结果（不可变）"""

    id: str
    name: str
    description: str
    source: str
    author: str
    install_url: str
    install_method: Literal["git", "zip", "direct"]
    version: str = ""
    stars: int = 0
    downloads: int = 0
    tags: list[str] = field(default_factory=list)
    readme_url: str | None = None
    subdirectory: str | None = None


@dataclass(frozen=True)
class SkillInstallResult:
    """技能安装结果（不可变）"""

    success: bool
    skill_name: str = ""
    skill_id: str = ""
    installed_path: str = ""
    error: str = ""
    error_code: str = ""
    """Machine-readable error code for UI/API branching (empty when not applicable)."""
    scan_summary: str = ""
    """Security scan summary (populated when scanner detects findings during install)"""


@dataclass(frozen=True, slots=True)
class InstalledSkillInfo:
    """Lightweight view of an installed skill for framework-layer consumers."""

    id: str
    name: str
    description: str
    version: str = ""
    tags: list[str] = field(default_factory=list)


@runtime_checkable
class InstalledSkillStore(Protocol):
    """Read-only access to installed skills (framework-layer protocol, business-layer impl)."""

    async def list_installed(
        self,
        *,
        user_id: str | None = None,
        skill_type: str | None = None,
    ) -> list[InstalledSkillInfo]: ...

    async def get_installed(self, skill_id: str) -> InstalledSkillInfo | None: ...


@runtime_checkable
class SkillDiscoveryBackend(Protocol):
    """技能发现后端协议（框架层定义，业务层实现）

    职责：搜索外部技能源、安装技能到本地存储。
    """

    async def search(
        self,
        query: str,
        limit: int = 10,
    ) -> list[SkillSearchResult]:
        """搜索技能

        Args:
            query: 搜索关键词（支持自然语言）
            limit: 最大返回数量

        Returns:
            匹配的技能列表（已排序、去重）
        """
        ...

    async def install(
        self,
        skill_id: str,
        source: str,
        user_id: str,
    ) -> SkillInstallResult:
        """安装技能

        根据部署模式自动选择安装方式：
        - Local: 安装到本地文件系统
        - Sandbox: 上传到对象存储

        Args:
            skill_id: 搜索结果中的技能 ID
            source: 技能来源
            user_id: 用户 ID

        Returns:
            安装结果
        """
        ...

    async def get_detail(
        self,
        skill_id: str,
        source: str,
    ) -> SkillSearchResult | None:
        """获取技能详情

        Args:
            skill_id: 技能 ID
            source: 技能来源

        Returns:
            技能详情，未找到返回 None
        """
        ...
