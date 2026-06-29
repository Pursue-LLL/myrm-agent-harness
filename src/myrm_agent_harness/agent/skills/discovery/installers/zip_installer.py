"""ZIP 技能安装器

从 URL 下载 ZIP 文件，通过框架层 safe_extract_zip 安全解压。

[INPUT]
- core.security.http.secure_fetch::secure_get (POS: SSRF-protected ZIP download)

[OUTPUT]
- ZipInstaller: class — Zip Installer

[POS]
Provides ZipInstaller.
"""

from __future__ import annotations

import logging

from myrm_agent_harness.backends.skills.scanning import safe_extract_zip

from .base import InstalledSkillFiles
from .git_installer import _parse_skill_md_metadata

logger = logging.getLogger(__name__)

ZIP_DOWNLOAD_TIMEOUT = 30.0
MAX_ZIP_SIZE = 50 * 1024 * 1024  # 50MB

_EXCLUDED_SEGMENTS = frozenset({".git", ".venv", "__pycache__", "node_modules"})


def _is_excluded_file(path: str) -> bool:
    parts = path.split("/")
    return any(part.startswith(".") or part in _EXCLUDED_SEGMENTS for part in parts)


class ZipInstaller:
    """ZIP 技能安装器

    下载 ZIP → safe_extract_zip 安全解压 → 定位 SKILL.md → 收集文件。
    """

    async def download(self, install_url: str, subdirectory: str | None = None) -> InstalledSkillFiles:
        zip_bytes = await self._download_zip(install_url)
        return self._extract_skill(zip_bytes, subdirectory)

    async def _download_zip(self, url: str) -> bytes:
        from myrm_agent_harness.core.security.http.secure_fetch import secure_get

        response = await secure_get(url, timeout=ZIP_DOWNLOAD_TIMEOUT)
        if response.status_code != 200:
            raise ValueError(f"ZIP download failed: HTTP {response.status_code}")

        content = response.content
        if len(content) > MAX_ZIP_SIZE:
            raise ValueError(f"ZIP too large: {len(content)} bytes (max {MAX_ZIP_SIZE})")
        return content

    def _extract_skill(self, zip_bytes: bytes, subdirectory: str | None) -> InstalledSkillFiles:
        all_files = safe_extract_zip(zip_bytes, strip_top_dir=True, forbidden_check=_is_excluded_file)

        if subdirectory:
            prefix = subdirectory.rstrip("/") + "/"
            files = {k[len(prefix) :]: v for k, v in all_files.items() if k.startswith(prefix)}
        else:
            if "SKILL.md" in all_files:
                files = all_files
            else:
                skill_md_candidates = [path for path in all_files if path.endswith("/SKILL.md")]
                if not skill_md_candidates:
                    raise ValueError("SKILL.md not found in ZIP")

                # Keep backward-compatible behavior: auto-select the shallowest skill root.
                skill_md_path = min(skill_md_candidates, key=lambda path: path.count("/"))
                root = skill_md_path.removesuffix("/SKILL.md")
                prefix = f"{root}/"
                files = {k[len(prefix) :]: v for k, v in all_files.items() if k.startswith(prefix)}

        if "SKILL.md" not in files:
            raise ValueError("SKILL.md not found in ZIP")

        name, description = _parse_skill_md_metadata(files["SKILL.md"])
        return InstalledSkillFiles(name=name, description=description, files=files)
