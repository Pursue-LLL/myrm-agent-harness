"""Runtime — skill execution runtime.

提供技能的运行时支持：
- registry: 技能注册表（运行时缓存）+ XML 摘要生成
- attenuator: 信任衰减器（最小信任原则 + 工具过滤）
- loader: SKILL.md 文档加载器
- env: 技能执行环境准备
"""

from .attenuator import AttenuationResult, attenuate_tools
from .env import (
    detect_skill_script_command,
    extract_skill_name,
    prepare_skill_env,
    resolve_skill_env,
    rewrite_skill_paths,
)
from .loader import SkillMdLoader, skill_md_loader
from .registry import SkillRegistry, get_metadata_summary, skill_registry

__all__ = [
    "AttenuationResult",
    "SkillMdLoader",
    "SkillRegistry",
    "attenuate_tools",
    "detect_skill_script_command",
    "extract_skill_name",
    "get_metadata_summary",
    "prepare_skill_env",
    "resolve_skill_env",
    "rewrite_skill_paths",
    "skill_md_loader",
    "skill_registry",
]
