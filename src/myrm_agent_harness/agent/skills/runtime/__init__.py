"""Runtime — skill execution runtime.

提供技能的运行时支持：
- registry: 技能注册表 + XML 摘要（供 HumanMessage ``<bound_skills>``）
- catalog_display: 内联/隐藏技能 SSOT
- skill_catalog_delivery: strip/reinject catalog on first HumanMessage
- attenuator: 信任衰减器
- loader: SKILL.md 文档加载器
- command_paths: 技能命令路径重写与技能脚本检测
"""

from .attenuator import AttenuationResult, attenuate_tools
from .catalog_display import (
    SKILL_CORE_MAX,
    SKILL_INLINE_THRESHOLD,
    SKILL_SELECT_INLINE_MAX,
    CatalogDisplayResolution,
    resolve_catalog_display_skills,
)
from .command_paths import (
    detect_skill_script_command,
    rewrite_skill_paths,
)
from .loader import SkillMdLoader, skill_md_loader
from .registry import SkillRegistry, get_metadata_summary, skill_registry
from .skill_catalog_delivery import (
    build_bound_skills_block,
    ensure_skill_catalog_in_messages,
    strip_catalog_blocks,
)

__all__ = [
    "SKILL_CORE_MAX",
    "SKILL_INLINE_THRESHOLD",
    "SKILL_SELECT_INLINE_MAX",
    "AttenuationResult",
    "CatalogDisplayResolution",
    "SkillMdLoader",
    "SkillRegistry",
    "attenuate_tools",
    "build_bound_skills_block",
    "detect_skill_script_command",
    "ensure_skill_catalog_in_messages",
    "get_metadata_summary",
    "resolve_catalog_display_skills",
    "rewrite_skill_paths",
    "skill_md_loader",
    "skill_registry",
    "strip_catalog_blocks",
]
