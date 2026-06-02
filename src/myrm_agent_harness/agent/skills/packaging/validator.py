"""技能包验证

提供技能 ZIP 包的验证、安全检查和元数据解析。

[INPUT]
- agent.skills.discovery.sanitizer::SKILL_MD_FILE, (POS: Provides is_blocked_file, sanitize_skill_files.)

[OUTPUT]
- SkillPackageInfo: class — Skill Package Info
- suggest_valid_skill_name: function — suggest_valid_skill_name
- is_forbidden_file: function — is_forbidden_file
- parse_skill_md: function — parse_skill_md
- validate_skill_zip: function — validate_skill_zip

[POS]
Provides SkillPackageInfo, suggest_valid_skill_name, is_forbidden_file.
"""

from __future__ import annotations

import io
import logging
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path

from myrm_agent_harness.agent.skills.discovery.sanitizer import SKILL_MD_FILE, SKILL_NAME_PATTERN

logger = logging.getLogger(__name__)

MAX_SKILL_ZIP_SIZE = 10 * 1024 * 1024  # 10MB

ALLOWED_EXTENSIONS = {
    ".py",
    ".js",
    ".ts",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".sh",
    ".bash",
    ".md",
    ".txt",
    ".rst",
    ".cfg",
    ".ini",
    ".env.example",
    ".css",
    ".scss",
    ".less",
    ".html",
    ".jinja",
    ".jinja2",
    ".j2",
}

FORBIDDEN_PATTERNS = [
    r"__pycache__",
    r"\.git",
    r"\.env$",
    r"\.pyc$",
    r"node_modules",
    r"venv",
    r"\.venv",
]


@dataclass
class SkillPackageInfo:
    """技能包信息"""

    name: str
    description: str
    version: str
    author: str | None
    files: list[str]
    is_valid: bool
    validation_errors: list[str]


def suggest_valid_skill_name(invalid_name: str) -> str:
    """将无效的技能名称转换为合法格式"""
    suggested = re.sub(r"[^a-zA-Z0-9_-]+", "-", invalid_name.strip())
    suggested = re.sub(r"^[^a-zA-Z]+", "", suggested)
    suggested = suggested.rstrip("-_").lower()
    return suggested or "my-skill"


def is_forbidden_file(file_path: str) -> bool:
    """检查文件是否在禁止列表中"""
    return any(re.search(pattern, file_path) for pattern in FORBIDDEN_PATTERNS)


def parse_skill_md(content: str) -> SkillPackageInfo:
    """解析 SKILL.md 文件

    支持 YAML front matter 和简单 YAML 格式。
    """
    name = ""
    description = ""
    version = "1.0.0"
    author = None

    lines = content.split("\n")
    in_front_matter = False
    front_matter_lines: list[str] = []

    for i, line in enumerate(lines):
        stripped = line.strip()
        if i == 0 and stripped == "---":
            in_front_matter = True
            continue
        if in_front_matter and stripped == "---":
            in_front_matter = False
            break
        if in_front_matter:
            front_matter_lines.append(line)

    target_lines = front_matter_lines if front_matter_lines else lines

    for line in target_lines:
        stripped = line.strip()
        if stripped.startswith("name:") and not name:
            name = stripped[5:].strip().strip('"').strip("'")
        elif stripped.startswith("description:") and not description:
            description = stripped[12:].strip().strip('"').strip("'")
        elif stripped.startswith("version:"):
            version = stripped[8:].strip().strip('"').strip("'")
        elif stripped.startswith("author:"):
            author = stripped[7:].strip().strip('"').strip("'")
        elif not front_matter_lines and stripped.startswith("# ") and not name:
            name = stripped[2:].strip()

    return SkillPackageInfo(
        name=name,
        description=description,
        version=version,
        author=author,
        files=[],
        is_valid=True,
        validation_errors=[],
    )


def validate_skill_zip(zip_content: bytes) -> SkillPackageInfo:
    """验证技能 ZIP 包"""
    errors: list[str] = []
    files: list[str] = []
    name = ""
    dir_name = ""
    description = ""
    version = "1.0.0"
    author = None

    empty_info = SkillPackageInfo(
        name="",
        description="",
        version="1.0.0",
        author=None,
        files=[],
        is_valid=False,
        validation_errors=errors,
    )

    try:
        if len(zip_content) > MAX_SKILL_ZIP_SIZE:
            errors.append(f"ZIP 文件过大 ({len(zip_content)} bytes > {MAX_SKILL_ZIP_SIZE} bytes)")

        with zipfile.ZipFile(io.BytesIO(zip_content), "r") as zf:
            namelist = zf.namelist()
            if not namelist:
                errors.append("ZIP 文件为空")
                return empty_info

            root_dirs = {n.split("/")[0] for n in namelist if n.split("/")[0]}

            if len(root_dirs) != 1:
                errors.append(f"ZIP 应该只包含一个根目录（技能目录），但发现: {root_dirs}")
            else:
                dir_name = next(iter(root_dirs))

            original_dir_name = dir_name

            if dir_name and not SKILL_NAME_PATTERN.match(dir_name):
                normalized_name = suggest_valid_skill_name(dir_name)
                logger.warning(
                    f" Skill directory name '{dir_name}' is invalid, automatically normalized to '{normalized_name}'"
                )
                name = normalized_name
            else:
                name = dir_name

            skill_md_path = f"{original_dir_name}/{SKILL_MD_FILE}" if original_dir_name else SKILL_MD_FILE
            if skill_md_path not in namelist:
                errors.append(f"缺少必需的 {SKILL_MD_FILE} 文件")
            else:
                try:
                    skill_md_content = zf.read(skill_md_path).decode("utf-8")
                    info = parse_skill_md(skill_md_content)
                    description = info.description
                    version = info.version
                    author = info.author
                except Exception as e:
                    errors.append(f"解析 {SKILL_MD_FILE} 失败: {e}")

            for name_in_zip in namelist:
                if name_in_zip.endswith("/"):
                    continue
                parts = name_in_zip.split("/", 1)
                relative_path = parts[1] if len(parts) > 1 else parts[0]

                if is_forbidden_file(relative_path):
                    continue

                ext = Path(relative_path).suffix.lower()
                if ext and ext not in ALLOWED_EXTENSIONS:
                    logger.warning(f"未知扩展名: {relative_path}")

                files.append(relative_path)

        return SkillPackageInfo(
            name=name,
            description=description,
            version=version,
            author=author,
            files=files,
            is_valid=len(errors) == 0,
            validation_errors=errors,
        )

    except zipfile.BadZipFile:
        errors.append("无效的 ZIP 文件")
        return empty_info
