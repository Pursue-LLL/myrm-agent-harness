"""Skills runtime — skill execution and management.

框架层技能模块，仅包含：
- runtime: 技能注册表、命令路径工具、信任衰减、目录投递
- mcp: MCP 技能生成和执行

业务层技能管理（CRUD、打包、用户配置）位于 app.core.skills。
"""

from myrm_agent_harness.backends.skills.types import SkillMetadata

from .runtime import (
    SkillRegistry,
    detect_skill_script_command,
    get_metadata_summary,
    rewrite_skill_paths,
    skill_registry,
)

__all__ = [
    # Metadata (from backends)
    "SkillMetadata",
    # Runtime
    "SkillRegistry",
    "detect_skill_script_command",
    "get_metadata_summary",
    "rewrite_skill_paths",
    "skill_registry",
]
