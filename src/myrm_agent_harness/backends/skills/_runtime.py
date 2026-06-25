"""Skill runtime builder — constructs SkillMetadata with runtime-computed fields.

1. 本文件的 INPUT/OUTPUT/POS 注释

[INPUT]
- types::SkillMetadata, SkillTrust (POS: 技能元数据类型和信任枚举)
- _utils::SkillFrontmatter (POS: 解析后的 frontmatter 数据)

[OUTPUT]
- build_skill_metadata(): 构建完整 SkillMetadata 的工厂函数（含 token 预算超制钳位）
- check_requirements(): 检查技能依赖是否满足
- compute_content_hash(): 计算内容 SHA-256 哈希
- scan_skill_content(): 技能内容安全扫描（软检测）

[POS]
Skill runtime builder. Constructs runtime metadata from static frontmatter data and runtime-computed results.

"""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
from pathlib import Path

from myrm_agent_harness.backends.skills._utils import SkillFrontmatter
from myrm_agent_harness.backends.skills.credential_validator import CredentialValidator
from myrm_agent_harness.backends.skills.scanning import compute_scan_summary, scan_skill_content
from myrm_agent_harness.backends.skills.types import (
    SkillMetadata,
    SkillTrust,
)
from myrm_agent_harness.utils.text_utils import get_token_count

logger = logging.getLogger(__name__)


def check_requirements(frontmatter: SkillFrontmatter) -> tuple[bool, str | None]:
    """Check if skill dependencies are satisfied.

    Returns:
        (available, unavailable_reason) tuple
    """
    if frontmatter.requires is None:
        return True, None

    missing: list[str] = []
    for b in frontmatter.requires.bins:
        if not shutil.which(b):
            missing.append(f"CLI: {b}")
    for env_var in frontmatter.requires.env:
        if not os.environ.get(env_var):
            missing.append(f"ENV: {env_var}")
    for cfg in frontmatter.requires.config:
        if not Path(cfg).exists():
            missing.append(f"CONFIG: {cfg}")

    if missing:
        return False, f"Missing: {', '.join(missing)}"
    return True, None


def compute_content_hash(content: str) -> str:
    """Compute SHA-256 hash of skill content for tamper detection.

    Line endings are normalized to LF before hashing for cross-platform consistency.
    """
    normalized = content.replace("\r\n", "\n").replace("\r", "\n")
    return f"sha256:{hashlib.sha256(normalized.encode('utf-8')).hexdigest()}"


def build_skill_metadata(
    skill_name: str,
    frontmatter: SkillFrontmatter,
    storage_path: str,
    content: str,
    trust: SkillTrust,
    workspace_root: Path | None = None,
) -> SkillMetadata:
    """Build SkillMetadata with all static and runtime-computed fields.

    This is the single factory function used by all backends to construct
    a complete SkillMetadata instance from parsed frontmatter data.

    Args:
        skill_name: Skill directory name (used as canonical name)
        frontmatter: Parsed SKILL.md frontmatter
        storage_path: Path where the skill is stored
        content: Raw SKILL.md content (for hash computation)
        trust: Trust level determined by source directory
        workspace_root: Optional workspace root for credential validation
    """
    available, unavailable_reason = check_requirements(frontmatter)
    scan_result = scan_skill_content(skill_name, content)
    allowed_tools = frontmatter.allowed_tools.split() if frontmatter.allowed_tools else None

    scan_summary = compute_scan_summary(scan_result)

    # Credential validation (if workspace_root provided)
    missing_credentials: list[str] = []
    if workspace_root and frontmatter.required_credential_files:
        validator = CredentialValidator(workspace_root)
        result = validator.validate_credential_files(frontmatter.required_credential_files)
        missing_credentials = result.missing_files

        if missing_credentials:
            logger.warning(
                "Skill '%s' missing credential files: %s",
                skill_name,
                ", ".join(missing_credentials),
            )

    # Validate declared tool group names against the canonical registry
    from myrm_agent_harness.core.security.tool_registry import TOOL_GROUP_NAMES

    for group_field_name, group_list in (
        ("requires_tool_groups", frontmatter.requires_tool_groups),
        ("fallback_for_tool_groups", frontmatter.fallback_for_tool_groups),
    ):
        invalid = [g for g in group_list if g not in TOOL_GROUP_NAMES]
        if invalid:
            logger.warning(
                "Skill '%s' declares %s=%s — unknown groups: %s (known: %s)",
                skill_name,
                group_field_name,
                group_list,
                invalid,
                sorted(TOOL_GROUP_NAMES),
            )

    return SkillMetadata(
        name=skill_name,
        description=frontmatter.description,
        storage_skill_id=skill_name,
        storage_path=storage_path,
        allowed_tools=allowed_tools,
        allowed_domains=frontmatter.allowed_domains,
        license=frontmatter.license,
        compatibility=frontmatter.compatibility,
        metadata=frontmatter.metadata,
        requires=frontmatter.requires,
        requires_tools=frontmatter.requires_tools,
        fallback_for_tools=frontmatter.fallback_for_tools,
        requires_tool_groups=frontmatter.requires_tool_groups,
        fallback_for_tool_groups=frontmatter.fallback_for_tool_groups,
        required_credential_files=frontmatter.required_credential_files,
        credential_env_mapping=frontmatter.credential_env_mapping,
        always=frontmatter.always,
        model_invocable=frontmatter.model_invocable,
        user_invocable=frontmatter.user_invocable,
        version=frontmatter.version,
        primary_env=frontmatter.primary_env,
        oauth_issuer=frontmatter.oauth_issuer,
        evolution_locked=frontmatter.evolution_locked,
        config_schema=frontmatter.config_schema,
        contract=frontmatter.contract,
        scope_agent_id=frontmatter.scope_agent_id,
        trust=trust,
        token_cost=get_token_count(content) if content else None,
        content_hash=compute_content_hash(content),
        available=available,
        unavailable_reason=unavailable_reason,
        missing_credentials=missing_credentials,
        scanner_clean=scan_result.is_clean,
        scan_summary=scan_summary,
    )
