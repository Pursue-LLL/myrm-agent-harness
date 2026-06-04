"""批量技能安装解析器 (针对 Hermes 等协议迁移)

负责解析上传的批量技能 ZIP，安全解压并映射到内部 DTO。
支持提取 Frontmatter (name, description, trigger_keywords) 转换为我们的规范。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

import yaml

from myrm_agent_harness.backends.skills.scanning.zip_extract import safe_extract_zip

logger = logging.getLogger(__name__)

_EXCLUDED_SEGMENTS = frozenset({".git", ".venv", "__pycache__", "node_modules", ".DS_Store", "__MACOSX"})

def _is_excluded_file(path: str) -> bool:
    parts = path.split("/")
    return any(part.startswith(".") or part in _EXCLUDED_SEGMENTS for part in parts)


@dataclass
class HermesImportedSkill:
    """从批量 ZIP 中解析出的单个技能 DTO"""
    name: str
    description: str
    content: str
    files: dict[str, bytes] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def skill_md_content(self) -> str:
        """获取 SKILL.md 原始内容"""
        return self.files.get("SKILL.md", b"").decode("utf-8", errors="replace")


class HermesBatchParser:
    """Hermes 批量技能解析器
    
    解析包含多个技能目录的 ZIP 包，安全解压后分类提取为 DTO 列表。
    """

    def parse_zip(self, zip_bytes: bytes) -> list[HermesImportedSkill]:
        """解析 ZIP 字节流为技能列表"""
        # safe_extract_zip 已内置防 Zip Bomb 和路径穿越的防御机制
        # strip_top_dir=False 保证我们能看到里面的不同技能目录
        all_files = safe_extract_zip(zip_bytes, strip_top_dir=False, forbidden_check=_is_excluded_file)

        # 按顶层目录对文件进行分组 (Hermes 的 skill 都是目录级组织)
        # 例如 skill_a/SKILL.md, skill_b/SKILL.md
        skill_groups: dict[str, dict[str, bytes]] = {}

        for path, content in all_files.items():
            parts = path.split("/")
            if len(parts) >= 2:
                top_dir = parts[0]
                rel_path = "/".join(parts[1:])
                if top_dir not in skill_groups:
                    skill_groups[top_dir] = {}
                skill_groups[top_dir][rel_path] = content
            elif path == "SKILL.md":
                # 直接位于根目录的技能
                if "." not in skill_groups:
                    skill_groups["."] = {}
                skill_groups["."][path] = content

        results: list[HermesImportedSkill] = []
        for dir_name, files in skill_groups.items():
            # 判断是否为合法技能：必须包含 SKILL.md 或者是 .md 文件直接构成
            skill_md_content = b""
            if "SKILL.md" in files:
                skill_md_content = files["SKILL.md"]
            else:
                # 寻找目录下的任何 md 文件作为备选
                md_files = [p for p in files if p.endswith(".md")]
                if md_files:
                    skill_md_content = files[md_files[0]]
                    # 模拟为 SKILL.md
                    files["SKILL.md"] = skill_md_content

            if not skill_md_content:
                logger.warning(f"Skip {dir_name}: No SKILL.md or markdown file found.")
                continue

            name, description, trigger_keywords, pure_content, metadata = self._parse_hermes_metadata(skill_md_content, fallback_name=dir_name)

            # 将 trigger_keywords 融入 description (适配我们的体系)
            if trigger_keywords:
                pattern_suffix = f"\n\n触发关键词(Patterns): {', '.join(trigger_keywords)}"
                description += pattern_suffix

            results.append(HermesImportedSkill(
                name=name,
                description=description,
                content=pure_content,
                files=files,
                metadata=metadata
            ))

        return results

    def _parse_hermes_metadata(self, content: bytes, fallback_name: str) -> tuple[str, str, list[str], str, dict]:
        """解析 Frontmatter 并分离元数据与正文"""
        text = content.decode("utf-8", errors="replace")

        # 匹配 Frontmatter
        match = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
        name = fallback_name if fallback_name != "." else "unnamed_skill"
        description = ""
        trigger_keywords: list[str] = []
        pure_content = text
        metadata = {}

        if match:
            pure_content = text[match.end():].strip()
            try:
                frontmatter = yaml.safe_load(match.group(1))
                if isinstance(frontmatter, dict):
                    metadata = frontmatter
                    name = str(frontmatter.get("name", name))
                    description = str(frontmatter.get("description", ""))
                    raw_keywords = frontmatter.get("trigger_keywords", [])
                    if isinstance(raw_keywords, list):
                        trigger_keywords = [str(k) for k in raw_keywords]
                    elif isinstance(raw_keywords, str):
                        trigger_keywords = [raw_keywords]
            except Exception as e:
                logger.warning(f"Failed to parse frontmatter for {fallback_name}: {e}")

        return name, description, trigger_keywords, pure_content, metadata
