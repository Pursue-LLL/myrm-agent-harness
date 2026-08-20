"""Agent Plugins 1.0.0 exporter and packaging builder.

Conforms to the open Agent Plugins 1.0.0 standard (https://agent-plugins.org).
Builds compliant plugin ZIP bundles containing plugin.json, skills/<name>/, and optional mcp.json.

[INPUT]
- manifest / metadata parameters
- skill file mapping

[OUTPUT]
- AgentPluginPacker: class for building standards-compliant Agent Plugins 1.0.0 packages
- canonical_plugin_name: helper to sanitize skill names to conform with spec §5.5

[POS]
Pure framework-level export utility. Zero business persistence, zero LLM dependencies.
"""

from __future__ import annotations

import io
import json
import logging
import re
import zipfile
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from myrm_agent_harness.agent.plugins.manifest import PLUGIN_SCHEMA
from myrm_agent_harness.agent.skills.market.sanitizer import SKILL_MD_FILE

logger = logging.getLogger(__name__)

# Spec §5.5: Lowercase alphanumeric, dots, hyphens; cannot start/end with -/. or have consecutive --/..
_VALID_NAME_RE = re.compile(r"^(?!.*(?:--|\.\.))[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?$")


def canonical_plugin_name(raw_name: str) -> str:
    """Sanitize a skill name into a valid Agent Plugins 1.0.0 plugin name (spec §5.5).

    Replaces underscores and spaces with hyphens, lowers case, and strips invalid chars.
    """
    cleaned = raw_name.strip().lower()
    cleaned = re.sub(r"[_\s]+", "-", cleaned)
    cleaned = re.sub(r"[^a-z0-9.-]", "", cleaned)
    cleaned = re.sub(r"-{2,}", "-", cleaned)
    cleaned = re.sub(r"\.{2,}", ".", cleaned)
    cleaned = cleaned.strip(".-")
    if not cleaned or not _VALID_NAME_RE.match(cleaned):
        return "myrm-skill-plugin"
    return cleaned


@dataclass
class PluginPackageResult:
    """Agent Plugin 打包结果"""

    success: bool
    zip_content: bytes | None
    filename: str | None
    error: str | None = None


class AgentPluginPacker:
    """Agent Plugins 1.0.0 规范打包器"""

    def build_plugin_manifest(
        self,
        name: str,
        version: str = "1.0.0",
        description: str | None = None,
        author_name: str = "Myrm User",
        author_url: str | None = None,
        keywords: list[str] | None = None,
        extensions: dict[str, Any] | None = None,
    ) -> str:
        """Render standard plugin.json manifest."""
        manifest: dict[str, Any] = {
            "$schema": PLUGIN_SCHEMA,
            "name": canonical_plugin_name(name),
            "version": version or "1.0.0",
            "description": description or f"Agent plugin for {name}",
        }

        if author_name:
            author_dict: dict[str, str] = {"name": author_name}
            if author_url:
                author_dict["url"] = author_url
            manifest["author"] = author_dict

        if keywords:
            manifest["keywords"] = list(dict.fromkeys(keywords))

        if extensions:
            manifest["extensions"] = extensions

        return json.dumps(manifest, indent=2, ensure_ascii=False)

    def package_skill_as_plugin(
        self,
        skill_name: str,
        file_contents: Mapping[str, bytes | str],
        *,
        version: str = "1.0.0",
        description: str | None = None,
        author_name: str = "Myrm User",
        keywords: list[str] | None = None,
        mcp_servers: dict[str, Any] | None = None,
        extra_extensions: dict[str, Any] | None = None,
    ) -> PluginPackageResult:
        """将技能文件集合打包为标准 Agent Plugins 1.0.0 ZIP 包。

        目录结构：
        - plugin.json (顶层清单)
        - mcp.json (可选顶层 MCP 配置)
        - skills/<canonical_name>/SKILL.md 及附属文件
        """
        from myrm_agent_harness.agent.skills.packaging.validator import (
            is_forbidden_file,
            parse_skill_md,
        )

        try:
            if SKILL_MD_FILE not in file_contents:
                return PluginPackageResult(
                    success=False,
                    zip_content=None,
                    filename=None,
                    error=f"缺少必需的 {SKILL_MD_FILE} 文件",
                )

            skill_info = parse_skill_md(
                file_contents[SKILL_MD_FILE].decode("utf-8")
                if isinstance(file_contents[SKILL_MD_FILE], bytes)
                else file_contents[SKILL_MD_FILE]
            )

            actual_name = skill_info.name or skill_name
            actual_version = skill_info.version or version
            actual_desc = (
                description or skill_info.description or f"Skill plugin {actual_name}"
            )

            plugin_name = canonical_plugin_name(actual_name)

            extensions: dict[str, Any] = {
                "ai.myrm.skill": {
                    "originalName": actual_name,
                    "exportedBy": "Myrm Agent Platform",
                }
            }
            if extra_extensions:
                extensions.update(extra_extensions)

            manifest_json = self.build_plugin_manifest(
                name=plugin_name,
                version=actual_version,
                description=actual_desc,
                author_name=author_name,
                keywords=keywords,
                extensions=extensions,
            )

            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
                # 1. 写入根目录 plugin.json
                zf.writestr(f"{plugin_name}/plugin.json", manifest_json.encode("utf-8"))

                # 2. 可选写入根目录 mcp.json
                if mcp_servers:
                    mcp_config = {
                        "$schema": "https://agent-plugins.org/schemas/1.0.0/mcp.schema.json",
                        "mcpServers": mcp_servers,
                    }
                    zf.writestr(
                        f"{plugin_name}/mcp.json",
                        json.dumps(mcp_config, indent=2, ensure_ascii=False).encode(
                            "utf-8"
                        ),
                    )

                # 3. 写入 skills/<plugin_name>/ 下的文件
                for fp, content in file_contents.items():
                    if is_forbidden_file(fp):
                        continue
                    if isinstance(content, str):
                        content = content.encode("utf-8")
                    zf.writestr(f"{plugin_name}/skills/{plugin_name}/{fp}", content)

            zip_content = zip_buffer.getvalue()
            filename = f"{plugin_name}_v{actual_version}.zip"

            logger.info(
                "Agent Plugin 打包完成: %s -> %s (%d bytes)",
                plugin_name,
                filename,
                len(zip_content),
            )
            return PluginPackageResult(
                success=True, zip_content=zip_content, filename=filename
            )

        except Exception as e:
            logger.error(
                "Agent Plugin 打包失败: %s, 错误: %s", skill_name, e, exc_info=True
            )
            return PluginPackageResult(
                success=False,
                zip_content=None,
                filename=None,
                error=str(e),
            )
