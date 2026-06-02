"""Storage Skill Backend (Pure Implementation)

1. 本文件的 INPUT/OUTPUT/POS 注释

[INPUT]
- protocols::SkillBackend (POS: 技能后端协议)
- types::SkillMetadata, SkillTrust (POS: 技能元数据类型和信任枚举)
- _utils::parse_skill_frontmatter (POS: 解析 SKILL.md frontmatter)
- _runtime::build_skill_metadata (POS: 构建完整 SkillMetadata 的工厂函数)
- storage.protocols::StorageBackend (POS: 存储后端协议，提供文件存取接口)

[OUTPUT]
- StorageSkillBackend: 存储技能后端（从存储后端加载技能，支持本地/S3/OSS，trust 可配置）

[POS]
Storage skill backend. Loads skills from any StorageBackend implementation (local/MinIO/S3/OSS).

"""

import logging

from myrm_agent_harness.backends.skills._runtime import build_skill_metadata
from myrm_agent_harness.backends.skills._utils import (
    _MAX_SKILL_FILE_SIZE,
    SkillMetadataError,
    parse_skill_frontmatter,
)
from myrm_agent_harness.backends.skills.protocols import SkillBackend
from myrm_agent_harness.backends.skills.types import SkillMetadata, SkillTrust
from myrm_agent_harness.toolkits.storage.base import StorageProvider

logger = logging.getLogger(__name__)


class StorageSkillBackend(SkillBackend):
    """Storage Skill Backend (Pure Implementation)

    Strictly follows Claude official Skills standard:
    - Only SKILL.md with YAML frontmatter
    - No metadata.json support
    - Clear error messages for invalid skills

    技能存储结构：
        {skills_prefix}/
        ├── skill_name/
        │   ├── SKILL.md           # 技能文档（必需）
        │   ├── scripts/           # 辅助脚本（可选）
        │   └── ...
    """

    def __init__(
        self,
        storage: StorageProvider,
        skills_prefix: str = "/skills",
        default_trust: SkillTrust = SkillTrust.INSTALLED,
    ):
        """Initialize storage skill backend.

        Args:
            storage: Storage backend instance (implements StorageBackend Protocol)
            skills_prefix: Skills storage path prefix
            default_trust: Trust level for skills loaded by this backend.
                INSTALLED (default) for user-uploaded/external skills.
                TRUSTED for official prebuilt skills.
        """
        self.storage = storage
        self.skills_prefix = skills_prefix.rstrip("/")
        self._default_trust = default_trust

    async def list_skills(self) -> list[SkillMetadata]:
        """List all skills by parsing SKILL.md frontmatter.

        Pure implementation:
        - Only loads skills with valid SKILL.md
        - Skips directories without SKILL.md
        - Reports detailed errors for invalid skills

        Returns:
            List of skill metadata (only valid skills)
        """
        skills: list[SkillMetadata] = []

        try:
            # List all files under skills prefix
            files = await self.storage.list(prefix=self.skills_prefix)

            # Extract skill directory names (deduplicate)
            skill_dirs = set()
            for file_path in files:
                # Parse path: /skills/skill_name/...
                relative_path = file_path[len(self.skills_prefix) :].lstrip("/")
                if "/" in relative_path:
                    skill_dir = relative_path.split("/")[0]
                    skill_dirs.add(skill_dir)

            logger.debug(f"Found {len(skill_dirs)} skill directories in storage")

            # Load each skill's metadata
            for skill_name in sorted(skill_dirs):
                try:
                    skill_metadata = await self._load_skill_metadata(skill_name)
                    if skill_metadata:
                        skills.append(skill_metadata)
                except Exception as e:
                    logger.error(f"Failed to load skill '{skill_name}': {e}")

        except Exception as e:
            logger.error(f"Failed to list skills from storage: {e}")

        logger.info(f"Loaded {len(skills)} valid skills from storage")
        return skills

    async def load_skills(self, skill_ids: list[str]) -> list[SkillMetadata]:
        """Load specified skills by IDs.

        Args:
            skill_ids: List of skill IDs (directory names)

        Returns:
            List of skill metadata (only valid skills)
        """
        skills: list[SkillMetadata] = []
        for skill_id in skill_ids:
            try:
                metadata = await self._load_skill_metadata(skill_id)
                if metadata:
                    skills.append(metadata)
            except Exception as e:
                logger.error(f"Failed to load skill '{skill_id}': {e}")
                continue
        return skills

    async def _load_skill_metadata(self, skill_name: str) -> SkillMetadata | None:
        """Load single skill's metadata by parsing SKILL.md.

        Pure implementation:
        - Only reads SKILL.md frontmatter
        - No fallback to metadata.json
        - Returns None if SKILL.md not found or invalid

        Args:
            skill_name: Skill name (directory name)

        Returns:
            Skill metadata, or None if loading failed
        """
        skill_path = f"{self.skills_prefix}/{skill_name}"
        skill_md_path = f"{skill_path}/SKILL.md"

        #  Require SKILL.md (official standard)
        if not await self.storage.exists(skill_md_path):
            logger.debug(
                f"Skipping '{skill_name}': no SKILL.md found. Skills must follow Claude official standard with SKILL.md"
            )
            return None

        #  Parse and validate (agentskills.io spec compliant)
        try:
            content = await self.storage.read_text(skill_md_path)

            #  File size check (skip files > 1 MB)
            content_size = len(content.encode("utf-8"))
            if content_size > _MAX_SKILL_FILE_SIZE:
                logger.warning(
                    f"Skipping '{skill_name}': SKILL.md is {content_size / 1024 / 1024:.1f} MB, "
                    f"exceeds {_MAX_SKILL_FILE_SIZE / 1024 / 1024:.0f} MB limit"
                )
                return None

            frontmatter = parse_skill_frontmatter(content, skill_name)

            return build_skill_metadata(
                skill_name=skill_name,
                frontmatter=frontmatter,
                storage_path=skill_path,
                content=content,
                trust=self._default_trust,
            )

        except SkillMetadataError as e:
            logger.error(f"Invalid skill '{skill_name}': {e}. Skipping this skill. See {skill_md_path} for details.")
            return None
        except Exception as e:
            logger.error(f"Failed to load skill '{skill_name}': {e}. Skipping this skill.")
            return None

    async def get_skill_content(self, skill_name: str) -> str:
        """Get skill content (SKILL.md).

        Args:
            skill_name: Skill name (directory name)

        Returns:
            Full SKILL.md content

        Raises:
            FileNotFoundError: If SKILL.md doesn't exist
        """
        skill_path = f"{self.skills_prefix}/{skill_name}/SKILL.md"

        try:
            if not await self.storage.exists(skill_path):
                raise FileNotFoundError(f"SKILL.md not found for skill '{skill_name}'. Expected path: {skill_path}")

            content = await self.storage.read_text(skill_path)
            logger.debug(f"Loaded SKILL.md for '{skill_name}' ({len(content)} chars)")
            return content
        except FileNotFoundError:
            raise
        except Exception as e:
            msg = f"Failed to load SKILL.md for '{skill_name}': {e}"
            logger.error(msg)
            raise FileNotFoundError(msg) from e

    async def get_skill_resources(self, skill_name: str, path: str) -> bytes:
        """Get a single skill resource file.

        Args:
            skill_name: Skill name (directory name)
            path: Relative path to the resource file

        Returns:
            File content as bytes

        Raises:
            FileNotFoundError: If resource file doesn't exist
        """
        full_path = f"{self.skills_prefix}/{skill_name}/{path}"
        try:
            return await self.storage.read(full_path)
        except FileNotFoundError:
            raise
        except Exception as e:
            raise FileNotFoundError(f"Failed to load resource '{path}' for skill '{skill_name}': {e}") from e

    async def list_skill_resources(self, skill_name: str) -> list[str]:
        """List all resource files for a skill (excluding SKILL.md)."""
        skill_prefix = f"{self.skills_prefix}/{skill_name}/"
        try:
            files = await self.storage.list(prefix=skill_prefix)
            return [f[len(skill_prefix) :] for f in files if not f.endswith("/SKILL.md")]
        except Exception as e:
            logger.error(f"Failed to list resources for skill '{skill_name}': {e}")
            return []
