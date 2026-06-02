"""技能打包

将技能打包为 ZIP 格式，支持：
- 从文件字典打包
- 从工作空间目录打包
- 从已注册的 SkillBackend 实例打包

[INPUT]
- agent.skills.discovery.sanitizer::SKILL_MD_FILE (POS: Provides is_blocked_file, sanitize_skill_files.)
- backends.skills.protocols::SkillBackend (POS: Protocols for Skill Optimization Subsystem)

[OUTPUT]
- PackageResult: class — Package Result
- SkillPacker: class — Skill Packer

[POS]
Provides PackageResult, SkillPacker.
"""

import io
import logging
import zipfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from myrm_agent_harness.agent.skills.discovery.sanitizer import SKILL_MD_FILE
from myrm_agent_harness.backends.skills.protocols import SkillBackend

from .validator import is_forbidden_file, parse_skill_md

logger = logging.getLogger(__name__)


@dataclass
class PackageResult:
    """打包结果"""

    success: bool
    zip_content: bytes | None
    filename: str | None
    error: str | None = None


class SkillPacker:
    """技能打包器"""

    def package_files(self, skill_name: str, version: str, file_contents: Mapping[str, bytes | str]) -> PackageResult:
        """从文件字典打包为 ZIP"""
        try:
            if SKILL_MD_FILE not in file_contents:
                return PackageResult(
                    success=False,
                    zip_content=None,
                    filename=None,
                    error=f"缺少必需的 {SKILL_MD_FILE} 文件",
                )

            # Ensure we're using the skill name and version from SKILL.md if possible
            skill_info = parse_skill_md(
                file_contents[SKILL_MD_FILE].decode("utf-8")
                if isinstance(file_contents[SKILL_MD_FILE], bytes)
                else file_contents[SKILL_MD_FILE]
            )

            actual_name = skill_info.name or skill_name
            actual_version = skill_info.version or version

            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
                for fp, content in file_contents.items():
                    if is_forbidden_file(fp):
                        continue
                    if isinstance(content, str):
                        content = content.encode("utf-8")
                    zf.writestr(f"{actual_name}/{fp}", content)

            zip_content = zip_buffer.getvalue()
            filename = f"{actual_name}_v{actual_version}.zip"

            logger.warning(f" 技能打包完成: {actual_name} -> {filename} ({len(zip_content)} bytes)")
            return PackageResult(success=True, zip_content=zip_content, filename=filename)

        except Exception as e:
            logger.error(f"技能文件打包失败: {skill_name}, 错误: {e}")
            return PackageResult(
                success=False,
                zip_content=None,
                filename=None,
                error=str(e),
            )

    async def package_from_backend(self, backend: SkillBackend, skill_name: str) -> PackageResult:
        """将已注册的技能（通过 SkillBackend 读取）打包为 ZIP"""
        try:
            skills = await backend.load_skills([skill_name])
            if not skills:
                return PackageResult(
                    success=False,
                    zip_content=None,
                    filename=None,
                    error=f"技能不存在: {skill_name}",
                )

            skill = skills[0]

            content = await backend.get_skill_content(skill_name)
            if not content:
                return PackageResult(
                    success=False,
                    zip_content=None,
                    filename=None,
                    error="技能内容为空",
                )

            resources = await backend.list_skill_resources(skill_name)

            file_contents: dict[str, bytes | str] = {SKILL_MD_FILE: content}

            for res_path in resources:
                res_content = await backend.get_skill_resources(skill_name, res_path)
                if res_content is not None:
                    file_contents[res_path] = res_content

            return self.package_files(skill.name, skill.version or "1.0.0", file_contents)

        except Exception as e:
            logger.error(f"从 Backend 打包失败: {skill_name}, 错误: {e}")
            return PackageResult(
                success=False,
                zip_content=None,
                filename=None,
                error=str(e),
            )

    def package_directory(self, directory_path: str | Path) -> PackageResult:
        """将本地目录打包为 ZIP"""
        try:
            search_dir = Path(directory_path)
            if not search_dir.exists() or not search_dir.is_dir():
                return PackageResult(
                    success=False,
                    zip_content=None,
                    filename=None,
                    error="目录为空或不存在",
                )

            file_contents: dict[str, bytes] = {}
            for p in search_dir.rglob("*"):
                if not p.is_file():
                    continue
                try:
                    rel = str(p.relative_to(search_dir))
                    file_contents[rel] = p.read_bytes()
                except Exception as e:
                    logger.warning(f"读取文件失败: {p}, {e}")

            if not file_contents:
                return PackageResult(
                    success=False,
                    zip_content=None,
                    filename=None,
                    error="目录为空或不存在",
                )

            skill_name = search_dir.name if search_dir.name else "custom_skill"
            return self.package_files(skill_name, "1.0.0", file_contents)

        except Exception as e:
            logger.error(f"目录打包失败: {directory_path}, 错误: {e}")
            return PackageResult(
                success=False,
                zip_content=None,
                filename=None,
                error=str(e),
            )
