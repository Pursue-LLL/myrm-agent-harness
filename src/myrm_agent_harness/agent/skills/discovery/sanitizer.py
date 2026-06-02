"""技能文件过滤与校验

上传技能时的文件清理：
- 过滤黑名单目录/文件（.venv, node_modules, __pycache__ 等）
- 校验单文件和总大小

[INPUT]
- (none)

[OUTPUT]
- is_blocked_file: function — is_blocked_file
- sanitize_skill_files: Raises:

[POS]
Provides is_blocked_file, sanitize_skill_files.
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

SKILL_NAME_PATTERN = re.compile(r"^[a-zA-Z][a-zA-Z0-9_-]*$")
SKILL_MD_FILE = "SKILL.md"

MAX_SINGLE_FILE_SIZE = 1 * 1024 * 1024  # 1MB
MAX_TOTAL_UPLOAD_SIZE = 5 * 1024 * 1024  # 5MB

_BLOCKED_PATH_SEGMENTS = frozenset(
    {
        ".venv",
        "venv",
        ".env",
        "node_modules",
        ".git",
        "__pycache__",
        ".tox",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "dist",
        "build",
        ".eggs",
        "*.egg-info",
    }
)

_BLOCKED_FILENAMES = frozenset(
    {
        ".DS_Store",
        "Thumbs.db",
        ".gitignore",
        ".gitattributes",
        "desktop.ini",
        ".npmrc",
        ".yarnrc",
    }
)


def is_blocked_file(filename: str) -> bool:
    """检查文件是否应被过滤"""
    parts = filename.replace("\\", "/").split("/")
    for part in parts:
        if part in _BLOCKED_PATH_SEGMENTS:
            return True
        if part.endswith(".egg-info"):
            return True
    basename = parts[-1] if parts else filename
    return basename in _BLOCKED_FILENAMES


def sanitize_skill_files(files: dict[str, bytes]) -> dict[str, bytes]:
    """过滤并校验技能文件

    Raises:
        ValueError: 文件大小超限或过滤后无有效文件
    """
    filtered: dict[str, bytes] = {}
    total_size = 0

    for filename, content in files.items():
        if is_blocked_file(filename):
            logger.warning(f" Blocked file filtered out: {filename}")
            continue

        file_size = len(content)
        if file_size > MAX_SINGLE_FILE_SIZE:
            raise ValueError(f"File '{filename}' exceeds size limit ({file_size} > {MAX_SINGLE_FILE_SIZE} bytes)")

        total_size += file_size
        if total_size > MAX_TOTAL_UPLOAD_SIZE:
            raise ValueError(f"Total upload size exceeds limit ({MAX_TOTAL_UPLOAD_SIZE} bytes)")

        filtered[filename] = content

    if not filtered:
        raise ValueError("No valid files after filtering blocked paths")

    return filtered
