"""
@input: 无外部依赖
@output: 对外提供技能配置版本号管理（bump/get）
@pos: 框架级技能配置版本追踪 —— Agent 轮询检测技能变更并热重载

🔄 更新规则：修改此文件后，请更新头注释 + 所属文件夹 _ARCH.md
"""

from __future__ import annotations

import time

_skill_config_versions: dict[str, float] = {}


def bump_skill_config_version() -> None:
    """Increment the skill config version.

    Agents can poll get_skill_config_version to detect changes
    and reload their skill set without restarting.
    """
    _skill_config_versions["sandbox"] = time.time()


def get_skill_config_version() -> float:
    """Return the current skill config version (0.0 if never changed)."""
    return _skill_config_versions.get("sandbox", 0.0)
