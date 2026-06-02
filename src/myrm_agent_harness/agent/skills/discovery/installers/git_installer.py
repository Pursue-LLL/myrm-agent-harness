"""Git 技能安装器

通过 git clone --depth 1 下载技能仓库，提取 SKILL.md 和相关文件。

[INPUT]
- (none)

[OUTPUT]
- GitInstaller: class — Git Installer

[POS]
Provides GitInstaller.
"""

from __future__ import annotations

import asyncio
import logging
import re
import shutil
import tempfile
from pathlib import Path

import yaml

from .base import InstalledSkillFiles

logger = logging.getLogger(__name__)

GIT_CLONE_TIMEOUT = 60


class GitInstaller:
    """Git 技能安装器

    浅克隆仓库 → 定位 SKILL.md → 收集文件 → 清理临时目录。
    """

    async def download(
        self, install_url: str, subdirectory: str | None = None, ref: str | None = None
    ) -> InstalledSkillFiles:
        """Download a skill from a git repository.

        Args:
            install_url: Git clone URL
            subdirectory: Optional subdirectory within the repo containing the skill
            ref: Optional branch, tag, or commit to checkout
        """
        tmp_dir = Path(tempfile.mkdtemp(prefix="skill_git_"))
        try:
            await self._git_clone(install_url, tmp_dir, ref=ref)
            skill_dir = self._resolve_skill_dir(tmp_dir, subdirectory)
            return self._collect_skill_files(skill_dir)
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    @staticmethod
    def _resolve_skill_dir(repo_root: Path, subdirectory: str | None) -> Path:
        """Resolve the actual skill directory within a cloned repo.

        Strategy: exact path → exact directory name match → substring match
        among all SKILL.md candidates. Handles cases where the skill name in
        the registry differs from the actual directory name in the repo.
        """
        if not subdirectory:
            return repo_root

        exact = repo_root / subdirectory
        if exact.exists() and (exact / "SKILL.md").exists():
            return exact

        skill_name = subdirectory.split("/")[-1].lower()
        candidates = [p for p in repo_root.rglob("SKILL.md") if ".git" not in p.parts]

        for candidate in candidates:
            if candidate.parent.name.lower() == skill_name:
                return candidate.parent

        for candidate in candidates:
            dir_name = candidate.parent.name.lower()
            if dir_name in skill_name or skill_name in dir_name:
                return candidate.parent

        if exact.exists():
            return exact

        if len(candidates) == 1:
            return candidates[0].parent

        return repo_root

    async def _git_clone(self, url: str, target: Path, *, ref: str | None = None) -> None:
        cmd = ["git", "clone", "--depth", "1", "--single-branch"]
        if ref:
            cmd.extend(["--branch", ref])
        cmd.extend([url, str(target)])

        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        try:
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=GIT_CLONE_TIMEOUT)
        except TimeoutError:
            proc.kill()
            raise ValueError(f"Git clone timed out after {GIT_CLONE_TIMEOUT}s: {url}") from None

        if proc.returncode != 0:
            error_msg = stderr.decode("utf-8", errors="replace").strip() if stderr else "unknown error"
            raise ValueError(f"Git clone failed: {error_msg}")

    def _collect_skill_files(self, skill_dir: Path) -> InstalledSkillFiles:
        skill_md_path = skill_dir / "SKILL.md"
        if not skill_md_path.exists():
            skill_md_path = _find_skill_md(skill_dir)
            if not skill_md_path:
                raise ValueError(f"SKILL.md not found in {skill_dir}")
            skill_dir = skill_md_path.parent

        files: dict[str, bytes] = {}
        name = skill_dir.name
        description = ""

        for item in _walk_skill_dir(skill_dir):
            rel_path = str(item.relative_to(skill_dir))
            try:
                files[rel_path] = item.read_bytes()
            except Exception as e:
                logger.warning(f"Failed to read {item}: {e}")

        if "SKILL.md" in files:
            name, description = _parse_skill_md_metadata(files["SKILL.md"])

        return InstalledSkillFiles(name=name, description=description, files=files)


def _find_skill_md(root: Path, max_depth: int = 3) -> Path | None:
    """在目录树中查找 SKILL.md（限制深度避免超大仓库扫描）"""
    if max_depth <= 0:
        return None
    try:
        for item in root.iterdir():
            if item.name == "SKILL.md" and item.is_file():
                return item
            if item.is_dir() and not item.name.startswith("."):
                result = _find_skill_md(item, max_depth - 1)
                if result:
                    return result
    except PermissionError:
        pass
    return None


def _walk_skill_dir(skill_dir: Path) -> list[Path]:
    """收集技能目录中的所有文件（排除隐藏文件和常见垃圾目录）"""
    excluded_dirs = {".git", ".venv", "__pycache__", "node_modules", ".mypy_cache"}
    files: list[Path] = []

    try:
        for item in skill_dir.rglob("*"):
            if (
                item.is_file()
                and not any(part.startswith(".") or part in excluded_dirs for part in item.parts)
                and item.relative_to(skill_dir).parts[0] not in excluded_dirs
            ):
                files.append(item)
    except PermissionError:
        pass

    return files


def _parse_skill_md_metadata(content: bytes) -> tuple[str, str]:
    """从 SKILL.md 解析 name 和 description"""
    text = content.decode("utf-8", errors="replace")
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
    if not match:
        return "unnamed_skill", ""
    try:
        frontmatter = yaml.safe_load(match.group(1))
        if isinstance(frontmatter, dict):
            name = str(frontmatter.get("name", "unnamed_skill"))
            description = str(frontmatter.get("description", ""))
            return name, description
    except Exception:
        pass
    return "unnamed_skill", ""
