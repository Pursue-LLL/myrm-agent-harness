"""Skills runtime — skill execution and management.

框架层技能模块，仅包含：
- runtime: 技能注册表、文档加载器、执行环境
- mcp: MCP 技能生成和执行

业务层技能管理（CRUD、打包、用户配置）位于 app.core.skills。
"""

from myrm_agent_harness.backends.skills.types import SkillMetadata

from .runtime import (
    SkillMdLoader,
    SkillRegistry,
    detect_skill_script_command,
    extract_skill_name,
    get_metadata_summary,
    prepare_skill_env,
    resolve_skill_env,
    rewrite_skill_paths,
    skill_md_loader,
    skill_registry,
)

__all__ = [
    "SkillMdLoader",
    # Metadata (from backends)
    "SkillMetadata",
    # Runtime
    "SkillRegistry",
    "detect_skill_script_command",
    "extract_skill_name",
    "get_metadata_summary",
    "prepare_skill_env",
    "resolve_skill_env",
    "rewrite_skill_paths",
    "skill_md_loader",
    "skill_registry",
]
