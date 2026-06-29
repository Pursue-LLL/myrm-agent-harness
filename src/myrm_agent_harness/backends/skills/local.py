"""Local Skill Backend (Pure Implementation)


[INPUT]
- protocols::SkillBackend (POS: 技能后端协议，定义统一接口)
- types::SkillMetadata, SkillTrust (POS: 技能元数据类型和信任枚举)
- _utils::parse_skill_frontmatter (POS: 解析 SKILL.md frontmatter)
- _runtime::build_skill_metadata (POS: 构建完整 SkillMetadata 的工厂函数)

[OUTPUT]
- LocalSkillBackend: 本地技能后端实现（从本地文件系统加载技能）
- scan_workspace_skills(): 递归扫描工作区目录中的 SKILL.md 文件

[POS]
Local skill backend. Loads skills from local paths following the official Claude Skills specification.

"""

import json
import logging
from pathlib import Path

from myrm_agent_harness.backends.skills._runtime import build_skill_metadata
from myrm_agent_harness.backends.skills._utils import (
    _MAX_SKILL_FILE_SIZE,
    SkillMetadataError,
    parse_skill_frontmatter,
)
from myrm_agent_harness.backends.skills.protocols import SkillBackend
from myrm_agent_harness.backends.skills.types import (
    SkillLifecycleStatus,
    SkillMetadata,
    SkillTrust,
    SkillUsageStats,
)

_STATS_FILENAME = ".stats.json"

logger = logging.getLogger(__name__)


class LocalSkillBackend(SkillBackend):
    """Local Skill Backend (Pure Implementation)

    Strictly follows Claude official Skills standard:
    - Only SKILL.md with YAML frontmatter
    - No metadata.json support
    - Clear error messages for invalid skills
    """

    def __init__(self, skills_dir: str | Path, use_snapshot: bool = True):
        """Initialize local skill backend.

        Args:
            skills_dir: Path to skills directory
            use_snapshot: If True, attempts to load from O(1) SQLite snapshot first

        Raises:
            FileNotFoundError: If skills directory doesn't exist
            ValueError: If path is not a directory
        """
        self.skills_dir = Path(skills_dir).resolve()  #  转换为绝对路径
        self.use_snapshot = use_snapshot

        if not self.skills_dir.exists():
            raise FileNotFoundError(
                f"Skills directory not found: {self.skills_dir}\nPlease ensure the directory exists or create it."
            )

        if not self.skills_dir.is_dir():
            raise ValueError(
                f"Skills path is not a directory: {self.skills_dir}\n"
                f"Expected a directory containing skill subdirectories."
            )

    async def list_skills(self) -> list[SkillMetadata]:
        """List all skills by parsing SKILL.md frontmatter.

        If use_snapshot is True, attempts to load from O(1) SQLite snapshot.
        Otherwise falls back to pure implementation:
        - Only loads skills with valid SKILL.md
        - Skips directories without SKILL.md
        - Reports detailed errors for invalid skills

        Returns:
            List of skill metadata (only valid skills)
        """
        if self.use_snapshot:
            snapshot_path = self.skills_dir / ".skills_snapshot.sqlite"
            if snapshot_path.exists():
                from myrm_agent_harness.backends.skills.snapshot import (
                    SQLiteSkillSnapshot,
                )

                snapshot = SQLiteSkillSnapshot(snapshot_path)
                snapshot_skills = snapshot.read_all()
                if snapshot_skills:
                    valid_snapshot_skills = []
                    for skill in snapshot_skills:
                        skill_dir = Path(skill.storage_path) if skill.storage_path else self.skills_dir / skill.name
                        usage_stats = self._read_lifecycle_stats(skill_dir)
                        if usage_stats is not None:
                            object.__setattr__(skill, "usage_stats", usage_stats)

                        if skill.usage_stats.lifecycle_status == SkillLifecycleStatus.ARCHIVED:
                            logger.debug(f"Skipping archived skill '{skill.name}' from snapshot")
                            continue
                        valid_snapshot_skills.append(skill)

                    logger.info(
                        f" Loaded {len(valid_snapshot_skills)} valid skills from fast O(1) snapshot at {self.skills_dir.name}"
                    )
                    return valid_snapshot_skills

        skills: list[SkillMetadata] = []

        for skill_dir in self.skills_dir.iterdir():
            if not skill_dir.is_dir():
                continue

            skill_name = skill_dir.name
            skill_md = skill_dir / "SKILL.md"

            #  Require SKILL.md (official standard)
            if not skill_md.exists():
                logger.debug(
                    f"Skipping '{skill_name}': no SKILL.md found "
                    f"(Claude official standard requires SKILL.md with YAML frontmatter)"
                )
                continue

            #  File size check (agentskills.io spec: skip files > 1 MB)
            file_size = skill_md.stat().st_size
            if file_size > _MAX_SKILL_FILE_SIZE:
                logger.warning(
                    f"Skipping '{skill_name}': SKILL.md is {file_size / 1024 / 1024:.1f} MB, "
                    f"exceeds {_MAX_SKILL_FILE_SIZE / 1024 / 1024:.0f} MB limit"
                )
                continue

            #  Parse and validate (agentskills.io spec compliant)
            try:
                content = skill_md.read_text(encoding="utf-8")
                frontmatter = parse_skill_frontmatter(content, skill_name)

                skill = build_skill_metadata(
                    skill_name=skill_name,
                    frontmatter=frontmatter,
                    storage_path=str(skill_dir),
                    content=content,
                    trust=SkillTrust.TRUSTED,
                )

                usage_stats = self._read_lifecycle_stats(skill_dir)
                if usage_stats is not None:
                    object.__setattr__(skill, "usage_stats", usage_stats)

                if skill.usage_stats.lifecycle_status == SkillLifecycleStatus.ARCHIVED:
                    logger.debug(f"Skipping archived skill '{skill_name}'")
                    continue

                skills.append(skill)
                logger.debug(f" Loaded skill '{skill_name}'")

            except SkillMetadataError as e:
                #  Validation error - use warning (expected issue)
                logger.warning(
                    f" Invalid skill '{skill_name}': {e}\n   Skipping this skill. Fix {skill_md} to resolve."
                )
            except UnicodeDecodeError as e:
                #  Encoding error - use warning
                logger.warning(f" Cannot read '{skill_name}/SKILL.md': {e}\n   Ensure file is UTF-8 encoded.")
            except Exception as e:
                #  Unexpected error - use error
                logger.error(
                    f" Unexpected error loading skill '{skill_name}': {e}\n   Skipping this skill.",
                    exc_info=True,  #  Include stack trace for debugging
                )

        logger.info(f"Loaded {len(skills)} valid skills from {self.skills_dir}")
        return skills

    async def load_skills(self, skill_ids: list[str]) -> list[SkillMetadata]:
        """Load specified skills by IDs.

        Args:
            skill_ids: List of skill IDs (directory names)

        Returns:
            List of skill metadata (only valid skills)
        """
        all_skills = await self.list_skills()
        return [skill for skill in all_skills if skill.name in skill_ids]

    async def get_skill_content(self, skill_name: str) -> str:
        """Get skill content (SKILL.md).

        Args:
            skill_name: Skill name (directory name)

        Returns:
            Full SKILL.md content

        Raises:
            FileNotFoundError: If SKILL.md doesn't exist
        """
        skill_md = self.skills_dir / skill_name / "SKILL.md"

        if not skill_md.exists():
            raise FileNotFoundError(f"SKILL.md not found for skill '{skill_name}'. Expected path: {skill_md}")

        return skill_md.read_text(encoding="utf-8")

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
        file_path = self.skills_dir / skill_name / path

        if not file_path.exists() or not file_path.is_file():
            raise FileNotFoundError(f"Resource not found: {path} in skill '{skill_name}'")

        return file_path.read_bytes()

    async def list_skill_resources(self, skill_name: str) -> list[str]:
        """List all resource files for a skill (excluding SKILL.md)."""
        skill_dir = self.skills_dir / skill_name
        if not skill_dir.exists():
            return []
        return [str(f.relative_to(skill_dir)) for f in skill_dir.rglob("*") if f.is_file() and f.name != "SKILL.md"]

    @staticmethod
    def _read_lifecycle_stats(skill_dir: Path) -> SkillUsageStats | None:
        """Read .stats.json and return SkillUsageStats if file exists.

        Returns None if no stats file exists (skill uses default stats).
        """
        stats_file = skill_dir / _STATS_FILENAME
        if not stats_file.exists():
            return None
        try:
            data = json.loads(stats_file.read_text(encoding="utf-8"))
            return SkillUsageStats.from_dict(data)
        except Exception:
            return None


_WORKSPACE_SKIP_DIRS = frozenset({".git", ".venv", "node_modules", "__pycache__", ".cache", "dist", "build"})


def scan_workspace_skills(
    workspace_root: str | Path,
    *,
    max_depth: int = 3,
    trust: SkillTrust = SkillTrust.INSTALLED,
    use_snapshot: bool = True,
) -> list[SkillMetadata]:
    """Recursively scan a workspace directory for SKILL.md files.

    Generic utility: any project using this framework can call this
    function to discover project-level skills.

    Args:
        workspace_root: Root directory to scan
        max_depth: Maximum recursion depth (default 3)
        trust: Trust level for discovered skills (default INSTALLED)
        use_snapshot: If True, attempts to load from O(1) SQLite snapshot first

    Returns:
        List of SkillMetadata for each valid skill found
    """
    root = Path(workspace_root).resolve()
    if not root.is_dir():
        return []

    if use_snapshot:
        snapshot_path = root / ".skills_snapshot.sqlite"
        if snapshot_path.exists():
            from myrm_agent_harness.backends.skills.snapshot import SQLiteSkillSnapshot

            snapshot = SQLiteSkillSnapshot(snapshot_path)
            snapshot_skills = snapshot.read_all(workspace_root=root)
            if snapshot_skills:
                valid_snapshot_skills = []
                for skill in snapshot_skills:
                    skill_dir = Path(skill.storage_path) if skill.storage_path else root / skill.name
                    usage_stats = LocalSkillBackend._read_lifecycle_stats(skill_dir)
                    if usage_stats is not None:
                        object.__setattr__(skill, "usage_stats", usage_stats)

                    if skill.usage_stats.lifecycle_status == SkillLifecycleStatus.ARCHIVED:
                        logger.debug(f"Skipping archived workspace skill '{skill.name}' from snapshot")
                        continue
                    valid_snapshot_skills.append(skill)

                logger.info(
                    " Scanned %d workspace skills from fast O(1) snapshot",
                    len(valid_snapshot_skills),
                )
                return valid_snapshot_skills

    skills: list[SkillMetadata] = []

    def _walk(directory: Path, depth: int) -> None:
        if depth > max_depth:
            return
        try:
            for item in directory.iterdir():
                if not item.is_dir() or item.name.startswith(".") or item.name in _WORKSPACE_SKIP_DIRS:
                    continue
                skill_md = item / "SKILL.md"
                if skill_md.exists():
                    _try_load_skill(item, skill_md, trust, skills)
                else:
                    _walk(item, depth + 1)
        except (PermissionError, OSError):
            pass

    _walk(root, 0)
    logger.info("Scanned %d workspace skills from %s", len(skills), root)
    return skills


def _try_load_skill(
    skill_dir: Path,
    skill_md: Path,
    trust: SkillTrust,
    result: list[SkillMetadata],
) -> None:
    """Attempt to load a single skill from a directory."""
    file_size = skill_md.stat().st_size
    if file_size > _MAX_SKILL_FILE_SIZE:
        return
    try:
        content = skill_md.read_text(encoding="utf-8")
        frontmatter = parse_skill_frontmatter(content, skill_dir.name)
        meta = build_skill_metadata(
            skill_name=skill_dir.name,
            frontmatter=frontmatter,
            storage_path=str(skill_dir),
            content=content,
            trust=trust,
        )
        result.append(meta)
    except (SkillMetadataError, UnicodeDecodeError):
        pass
    except Exception as e:
        logger.warning("Unexpected error loading workspace skill '%s': %s", skill_dir.name, e)
