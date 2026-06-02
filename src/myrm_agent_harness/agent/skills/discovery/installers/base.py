"""技能安装器 Protocol

[INPUT]
- (none)

[OUTPUT]
- InstalledSkillFiles: class — Installed Skill Files
- SkillInstaller: class — Skill Installer

[POS]
Provides InstalledSkillFiles, SkillInstaller.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class InstalledSkillFiles:
    """安装后的技能文件集合"""

    name: str
    description: str
    files: dict[str, bytes]


@runtime_checkable
class SkillInstaller(Protocol):
    """技能安装器协议

    负责从外部源下载技能文件。
    不负责最终存储（由 SkillDiscoveryService 决定存储位置）。
    """

    async def download(self, install_url: str, subdirectory: str | None = None) -> InstalledSkillFiles:
        """下载技能文件

        Args:
            install_url: 安装 URL（git URL 或 ZIP URL）
            subdirectory: 技能所在子目录（如 'skills/react-optimizer'）

        Returns:
            技能文件集合

        Raises:
            ValueError: 下载失败或 SKILL.md 缺失
        """
        ...
