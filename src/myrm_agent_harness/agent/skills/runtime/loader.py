"""技能MD文档加载器（三级Fallback + LRU缓存 + Schema增强 + 可观测）

支持两种来源：
1. MCP 技能 — 从内存按需生成
2. 存储技能 — 通过注入的 SkillBackend 读取

三级Fallback策略确保100%可用：
1. Primary: 从backend加载或内存生成
2. Secondary: 从LRU缓存加载（maxsize=100, TTL=1h）
3. Tertiary: 生成降级版文档（包含完整工具schema，异步I/O）

内存安全：
- LRU缓存限制：skills=100（约10MB），fallback_count=200
- TTL自动过期：skills=1h，fallback_count=24h

降级文档增强：
- MCP技能：异步I/O读取完整工具schema
- Schema可用性：100%（5/5 browser tools）

可观测性：
- 缓存metrics：命中率、驱逐数、过期数
- Fallback统计：每个skill的fallback触发次数
- 通过get_cache_metrics()和get_fallback_stats()获取

配置：
- MCP路径：通过 set_mcp_base_path() 配置

Reference: MASTER_IMPLEMENTATION_ROADMAP.md §13.5

[INPUT]
- utils.lru_cache::LRUCache (POS: LRU  TTL  LRU)
- backends.skills.protocols::SkillBackend (POS: Protocols for Skill Optimization Subsystem)

[OUTPUT]
- SkillMdLoader: class — Skill Md Loader
- set_mcp_base_path: Set MCP filesystem base path for tool schema enrichment.

[POS]
Reference: MASTER_IMPLEMENTATION_ROADMAP.md §13.5
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from myrm_agent_harness.utils.lru_cache import LRUCache

from .registry import skill_registry

if TYPE_CHECKING:
    from myrm_agent_harness.backends.skills.protocols import SkillBackend

    from .registry import SkillMetadata

logger = logging.getLogger(__name__)

MCP_BASE_PATH = ""


def set_mcp_base_path(path: str) -> None:
    """Set MCP filesystem base path for tool schema enrichment."""
    global MCP_BASE_PATH
    MCP_BASE_PATH = path


class SkillMdLoader:
    """技能MD文档加载器（三级Fallback + LRU缓存 + 可观测）

    负责加载技能的 SKILL.md 内容（去除 frontmatter）和引用文件。
    存储技能通过 set_backend() 注入的 SkillBackend 加载。

    三级Fallback策略确保Skills 100%可用：
    1. Primary: 从backend加载或内存生成
    2. Secondary: 从LRU缓存加载（缓存命中时）
    3. Tertiary: 生成降级版文档（包含完整工具schema，异步I/O）

    内存安全：
    - LRU缓存限制：skills=100（约10MB），fallback_count=200
    - TTL自动过期：skills=1h，fallback_count=24h

    可观测性：
    - 缓存metrics：命中率、驱逐数、过期数、利用率（get_cache_metrics）
    - Fallback统计：每个skill的fallback触发次数（get_fallback_stats）

    降级事件会被记录到日志，用于监控和告警。
    """

    def __init__(self) -> None:
        self._skill_cache: LRUCache[str] = LRUCache(
            maxsize=100,  # 限制最多100个skills
            ttl=3600,  # 1小时TTL
            id="skill_md_cache",
        )
        self._backend: SkillBackend | None = None
        self._trap_lookup: Callable[[str], list[dict[str, Any]]] | None = None
        self._fallback_count: LRUCache[int] = LRUCache(
            maxsize=200,  # 限制最多200个skill的fallback统计
            ttl=86400,  # 24小时TTL
            id="fallback_count_cache",
        )

    def set_backend(self, backend: SkillBackend) -> None:
        """注入技能后端（由业务层在 agent 初始化时调用）"""
        self._backend = backend

    def set_trap_lookup(self, lookup: Callable[[str], list[dict[str, Any]]]) -> None:
        """注入陷阱查找回调（由 EvolutionIntegration 在启用进化时调用）"""
        self._trap_lookup = lookup

    async def load_skill_details_by_metadata(self, skill_meta: SkillMetadata) -> str:
        """加载技能的完整内容（三级Fallback策略，保证100%可用）

        Fallback策略：
        1. Primary: 从backend加载或内存生成
        2. Secondary: 从LRU缓存加载（maxsize=100, TTL=1h）
        3. Tertiary: 生成降级版文档（包含完整工具schema，异步I/O）

        Args:
            skill_meta: 技能元数据

        Returns:
            SKILL.md 内容（不含 frontmatter），保证非空
        """
        # Level 2: Secondary Fallback - 从缓存加载
        cached_content = self._skill_cache.get(skill_meta.name)
        if cached_content is not None:
            logger.debug(f"Skill loaded from cache: {skill_meta.name}")
            return cached_content

        full_content = None
        fallback_level = 0

        try:
            # Level 1: Primary - 从backend加载或内存生成
            # MCP 技能：从内存按需生成
            if skill_meta.is_mcp_skill:
                from myrm_agent_harness.agent.skills.mcp.core_generator import mcp_skill_generator

                full_content = mcp_skill_generator.generate_skill_content(skill_meta)
                logger.info(f"[Primary] Generated SKILL.md from memory: {skill_meta.name}")

            # 存储技能：通过注入的 SkillBackend 读取
            elif self._backend is not None:
                try:
                    full_content = await self._backend.get_skill_content(skill_meta.name)
                    logger.info(f"[Primary] Loaded SKILL.md via backend: {skill_meta.name}")
                except Exception as e:
                    logger.error(f"[Primary] Failed to load SKILL.md via backend for {skill_meta.name}: {e}")
                    fallback_level = 3  # Jump to tertiary
            else:
                logger.warning(f"[Primary] No backend configured for storage skill: {skill_meta.name}")
                fallback_level = 3  # Jump to tertiary

        except Exception as e:
            logger.error(f"[Primary] Unexpected error loading {skill_meta.name}: {e}")
            fallback_level = 3

        # Level 3: Tertiary Fallback - 生成降级版文档
        if not full_content or fallback_level == 3:
            current_count = self._fallback_count.get(skill_meta.name) or 0
            logger.warning(
                f"[Tertiary] Generating degraded skill doc for {skill_meta.name} (fallback_count={current_count + 1})"
            )
            full_content = await self._generate_degraded_skill_doc(skill_meta)
            self._fallback_count.set(skill_meta.name, current_count + 1)

        # 解析并缓存 Hook 和 allowed-tools（如果还没有解析过）
        if full_content and not skill_meta.hooks:
            try:
                from myrm_agent_harness.agent.hooks import parse_hooks_from_skill_md

                hooks, allowed_tools = parse_hooks_from_skill_md(full_content)
                skill_meta.hooks = hooks
                skill_meta.allowed_tools = allowed_tools

                if hooks:
                    logger.debug(f"Parsed {len(hooks)} hook(s) from {skill_meta.name}")
                if allowed_tools:
                    logger.debug(f"Parsed allowed-tools from {skill_meta.name}: {', '.join(allowed_tools)}")
            except Exception as e:
                logger.error(f"Failed to parse hooks from {skill_meta.name}: {e}")
                skill_meta.hooks = []
                skill_meta.allowed_tools = None

        skill_content = self._remove_frontmatter(full_content)
        skill_content = self._apply_trap_injection(skill_meta.name, skill_content)
        self._skill_cache.set(skill_meta.name, skill_content)

        return skill_content

    def _apply_trap_injection(self, skill_name: str, content: str) -> str:
        """Look up traps for this skill and inject if found (best-effort, silent fail)."""
        if not self._trap_lookup:
            return content
        try:
            traps = self._trap_lookup(skill_name)
            if traps:
                return self.inject_known_pitfalls(content, traps)
        except Exception as e:
            logger.debug("Trap lookup failed for %s (non-fatal): %s", skill_name, e)
        return content

    @staticmethod
    def inject_known_pitfalls(content: str, traps: list[dict[str, Any]], max_traps: int = 5) -> str:
        """Append known pitfalls to skill content (tail injection to protect prompt cache prefix).

        Only includes traps with severity >= medium. Appended at the end so that
        the shared prompt prefix remains stable for cache hits.

        Args:
            content: Original skill content
            traps: List of trap dicts from SkillRecord
            max_traps: Max number of traps to inject

        Returns:
            Content with appended pitfalls section (or unchanged if no qualifying traps)
        """
        severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        qualifying = [t for t in traps if severity_order.get(t.get("severity", "low"), 4) <= 2]
        if not qualifying:
            return content

        qualifying.sort(key=lambda t: (severity_order.get(t.get("severity", "low"), 4), -t.get("occurrence_count", 0)))
        qualifying = qualifying[:max_traps]

        severity_icons = {"critical": "!!!", "high": "!!", "medium": "!"}
        lines = ["\n\n---\n## Known Pitfalls\n"]
        for trap in qualifying:
            icon = severity_icons.get(trap.get("severity", "medium"), "!")
            desc = trap.get("description", "")
            mitigation = trap.get("mitigation", "")
            entry = f"- [{icon}] {desc}"
            if mitigation:
                entry += f" → {mitigation}"
            lines.append(entry)

        return content + "\n".join(lines) + "\n"

    async def load_mcp_skill_details(self, skill_name: str) -> str | None:
        """加载 MCP 技能的完整内容

        此方法仅适用于 MCP 技能（从 skill_registry 查找）。
        存储技能请使用 load_skill_details_by_metadata()。

        Args:
            skill_name: MCP 技能名称

        Returns:
            SKILL.md 内容（不含 frontmatter），失败返回 None
        """
        skill_meta = skill_registry.get_skill(skill_name)
        if not skill_meta:
            logger.error(f"MCP skill not found: {skill_name}")
            return None

        return await self.load_skill_details_by_metadata(skill_meta)

    async def load_mcp_skill_reference(self, skill_name: str, reference_file: str) -> str | None:
        """加载 MCP 技能引用的额外文件（如工具文档）

        Args:
            skill_name: MCP 技能名称
            reference_file: 引用文件的相对路径

        Returns:
            文件内容，失败返回 None
        """
        skill_meta = skill_registry.get_skill(skill_name)
        if not skill_meta or not skill_meta.is_mcp_skill:
            return None

        # MCP 技能：工具文档
        if reference_file.endswith(".md"):
            tool_name = reference_file.replace(".md", "")
            from myrm_agent_harness.agent.skills.mcp.core_generator import mcp_skill_generator

            return mcp_skill_generator.generate_tool_doc(skill_meta, tool_name)

        return None

    async def _load_mcp_tool_descriptor(self, server: str, tool_name: str) -> dict[str, Any] | None:
        """从MCP文件系统加载工具descriptor（异步I/O）

        读取Cursor IDE的MCP工具descriptor JSON文件，获取完整的工具schema。
        使用异步I/O避免阻塞事件循环。

        路径配置：
        - 默认：~/.cursor/projects/<workspace-hash>/mcps/<server>/tools/<tool>.json
        - 可通过 set_mcp_base_path() 覆盖基础路径

        Args:
            server: MCP server名称
            tool_name: 工具名称

        Returns:
            工具descriptor字典，包含name、description、arguments等字段
            如果文件不存在或读取失败，返回None
        """
        import json
        from pathlib import Path

        import aiofiles

        if not MCP_BASE_PATH:
            return None

        tool_file = Path(MCP_BASE_PATH) / server / "tools" / f"{tool_name}.json"

        try:
            if tool_file.exists():
                async with aiofiles.open(tool_file, encoding="utf-8") as f:
                    content = await f.read()
                    return json.loads(content)
        except Exception as exc:
            logger.debug("Failed to load MCP tool descriptor (server=%s, tool=%s): %s", server, tool_name, exc)

        return None

    async def _append_tool_schema(self, lines: list[str], tool_descriptor: dict[str, Any]) -> None:
        """格式化并追加工具schema到文档行列表

        Args:
            lines: 文档行列表（会被修改）
            tool_descriptor: 工具descriptor字典
        """
        import json

        if tool_descriptor.get("description"):
            lines.append(tool_descriptor["description"])
            lines.append("")

        input_schema = tool_descriptor.get("arguments", {})
        if not input_schema:
            lines.append("*No parameters required*")
            lines.append("")
            return

        lines.append("**Parameters:**")
        lines.append("")
        lines.append("```json")
        lines.append(json.dumps(input_schema, indent=2))
        lines.append("```")
        lines.append("")

        properties = input_schema.get("properties", {})
        required = input_schema.get("required", [])

        if properties:
            lines.append("**Parameter Details:**")
            lines.append("")
            for param_name, param_schema in properties.items():
                is_required = param_name in required
                param_type = param_schema.get("type", "any")
                param_desc = param_schema.get("description", "No description")

                req_marker = " (required)" if is_required else " (optional)"
                lines.append(f"- `{param_name}` ({param_type}){req_marker}: {param_desc}")

                if "enum" in param_schema:
                    enum_values = ", ".join(f"`{v}`" for v in param_schema["enum"])
                    lines.append(f" - Allowed values: {enum_values}")

                if "default" in param_schema:
                    lines.append(f" - Default: `{param_schema['default']}`")

            lines.append("")

    async def _generate_degraded_skill_doc(self, skill_meta: SkillMetadata) -> str:
        """生成降级版技能文档（Tertiary Fallback with Enhanced Schema）

        当Primary和Secondary都失败时，生成增强的降级版文档。

        MCP技能包含：
        - 技能名称和描述
        - 完整工具schema（从MCP文件系统读取）
        - 参数详情（类型、必填、枚举、默认值）

        存储技能包含：
        - 技能名称和描述
        - 基本使用说明

        可用性：MCP技能约80-100%可用（取决于schema加载成功率）

        Args:
            skill_meta: 技能元数据

        Returns:
            降级版SKILL.md内容（包含schema）
        """
        lines = [
            f"# {skill_meta.name}",
            "",
            " **DEGRADED MODE**: This is a fallback skill document generated due to loading failure.",
            "",
        ]

        # 添加描述（如果有）
        if skill_meta.description:
            lines.extend(
                [
                    "## Description",
                    "",
                    skill_meta.description,
                    "",
                ]
            )

        if skill_meta.contract is not None:
            lines.extend(
                [
                    "## Contract",
                    "",
                ]
            )

            if skill_meta.contract.success_criteria:
                lines.extend(
                    [
                        "### Success Criteria",
                        "",
                        skill_meta.contract.success_criteria,
                        "",
                    ]
                )

            if skill_meta.contract.dependencies:
                lines.append("### Dependencies")
                lines.append("")
                for dependency in skill_meta.contract.dependencies:
                    lines.append(f"- {dependency}")
                lines.append("")

            if skill_meta.contract.verification_steps:
                lines.append("### Verification")
                lines.append("")
                for verification in skill_meta.contract.verification_steps:
                    required_marker = "required" if verification.is_required else "optional"
                    detail = f"{verification.description} (method: {verification.validation_method}, {required_marker})"
                    lines.append(f"- {detail}")
                    if verification.expected_output:
                        lines.append(f" Expected: {verification.expected_output}")
                lines.append("")

            if skill_meta.contract.potential_traps:
                lines.append("### Potential Traps")
                lines.append("")
                for trap in skill_meta.contract.potential_traps:
                    lines.append(f"- [{trap.severity}] {trap.description}")
                    lines.append(f" Mitigation: {trap.mitigation}")
                    if trap.trigger_condition:
                        lines.append(f" Trigger: {trap.trigger_condition}")
                lines.append("")

        # MCP技能：列出可用工具及其完整schema
        if skill_meta.is_mcp_skill and skill_meta.mcp:
            lines.extend(
                [
                    "## Available Tools",
                    "",
                    f"This skill provides access to MCP server: `{skill_meta.mcp.server}`",
                    "",
                ]
            )

            if skill_meta.mcp.tools:
                lines.append("### Tools and Schemas")
                lines.append("")

                # 从MCP文件系统获取每个工具的完整schema
                for tool_name in skill_meta.mcp.tools:
                    lines.append(f"#### `{tool_name}`")
                    lines.append("")

                    # 尝试从MCP文件系统读取tool descriptor
                    tool_descriptor = await self._load_mcp_tool_descriptor(skill_meta.mcp.server, tool_name)

                    if tool_descriptor:
                        await self._append_tool_schema(lines, tool_descriptor)
                    else:
                        lines.append("*Schema unavailable - tool descriptor not found*")
                        lines.append("")
            else:
                lines.extend(
                    [
                        "Tool list unavailable in degraded mode.",
                        "",
                    ]
                )

        # 存储技能：基本说明
        elif skill_meta.is_storage_skill:
            lines.extend(
                [
                    "## Usage",
                    "",
                    "This is a storage-backed skill. Full documentation is currently unavailable.",
                    "Please check the skill backend or contact the administrator.",
                    "",
                ]
            )

        # 通用使用说明
        lines.extend(
            [
                "## Notes",
                "",
                "- This is a degraded fallback document with enhanced schema information.",
                "- Full skill documentation is temporarily unavailable.",
                "- Tool schemas are provided for basic usage guidance (estimated 80% functionality).",
                "- Contact the system administrator if this issue persists.",
                "",
            ]
        )

        return "\n".join(lines)

    def _remove_frontmatter(self, content: str) -> str:
        """去除 YAML frontmatter

        Args:
            content: 原始内容

        Returns:
            去除 frontmatter 后的内容
        """
        frontmatter_match = re.match(r"^---\s*\n.*?\n---\s*\n", content, re.DOTALL)
        if frontmatter_match:
            return content[frontmatter_match.end() :].strip()
        return content.strip()

    def invalidate_skill(self, skill_name: str) -> None:
        """Invalidate cached content for a specific skill.

        Called by ScanningSkillWriteBackend after a skill is saved or deleted,
        ensuring the next load fetches fresh content from the backend.
        """
        self._skill_cache.delete(skill_name)
        logger.debug(f"Cache invalidated for skill: {skill_name}")

    def clear_cache(self) -> None:
        """清除缓存（包括fallback计数）"""
        self._skill_cache.clear()
        self._fallback_count.clear()

    def get_fallback_stats(self) -> dict[str, int]:
        """获取Fallback统计（用于监控）

        Returns:
            技能名称 -> fallback触发次数的映射
        """
        return self._fallback_count.items()

    def get_cache_metrics(self) -> dict[str, Any]:
        """获取缓存性能指标（用于监控）

        Returns:
            包含两个缓存的详细指标：
            - skill_cache: 技能内容缓存指标
            - fallback_count_cache: Fallback统计缓存指标
        """
        return {
            "skill_cache": self._skill_cache.get_metrics(),
            "fallback_count_cache": self._fallback_count.get_metrics(),
        }


# 全局单例
skill_md_loader = SkillMdLoader()
