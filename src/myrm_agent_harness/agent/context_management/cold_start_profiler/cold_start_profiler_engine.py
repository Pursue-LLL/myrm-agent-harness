"""Cold Start Context Profiler Engine providing transparent context breakdown.

Inspects baseline token footprints across system prompt, built-in core tools,
external MCP schemas, and memory, generating visual profiling and sleep suggestions.
"""

from __future__ import annotations

import json
from typing import Sequence

from .cold_start_profiler_types import (
    ColdStartContextProfile,
    ContextComponentKind,
    ContextComponentProfile,
    McpServerDescriptor,
    McpServerMountState,
)


class ColdStartContextProfilerEngine:
    """Engine analyzing initial context consumption before the first turn begins."""

    def __init__(
        self,
        mcp_warning_token_threshold: int = 5000,
        mcp_warning_ratio_threshold: float = 0.40,
    ) -> None:
        self.mcp_warning_token_threshold = mcp_warning_token_threshold
        self.mcp_warning_ratio_threshold = mcp_warning_ratio_threshold

    def profile_cold_start(
        self,
        session_id: str,
        system_prompt: str,
        core_tools: Sequence[dict[str, object]] | None = None,
        mcp_servers: Sequence[McpServerDescriptor] | None = None,
        instruction_memory: str | None = None,
    ) -> ColdStartContextProfile:
        """Construct detailed breakdown of cold start context payload."""
        components: list[ContextComponentProfile] = []
        raw_mcp_list = list(mcp_servers or [])

        # 1. System Prompt Profile
        sys_chars = len(system_prompt)
        sys_tokens = max(1, sys_chars // 4)
        components.append(
            ContextComponentProfile(
                kind=ContextComponentKind.SYSTEM_PROMPT,
                name="System Prompt",
                character_count=sys_chars,
                estimated_tokens=sys_tokens,
                percentage=0.0,
            )
        )

        # 2. Built-in Core Tools Profile
        core_chars = 0
        if core_tools:
            core_chars = sum(len(json.dumps(t, ensure_ascii=False)) for t in core_tools)
        core_tokens = max(0, core_chars // 4)
        components.append(
            ContextComponentProfile(
                kind=ContextComponentKind.CORE_TOOLS,
                name="Core Built-in Tools",
                character_count=core_chars,
                estimated_tokens=core_tokens,
                percentage=0.0,
                details={"tool_count": str(len(core_tools or []))},
            )
        )

        # 3. External MCP Tools Profile (Only active mounted servers)
        active_mcp = [s for s in raw_mcp_list if s.mount_state == McpServerMountState.MOUNTED_ACTIVE]
        mcp_tokens = sum(s.estimated_schema_tokens for s in active_mcp)
        mcp_chars = mcp_tokens * 4
        mcp_server_names = [s.display_name for s in active_mcp]
        components.append(
            ContextComponentProfile(
                kind=ContextComponentKind.MCP_EXTERNAL_TOOLS,
                name="External MCP Tools",
                character_count=mcp_chars,
                estimated_tokens=mcp_tokens,
                percentage=0.0,
                details={
                    "active_servers": ", ".join(mcp_server_names) if mcp_server_names else "none",
                    "total_tools": str(sum(len(s.tool_names) for s in active_mcp)),
                },
            )
        )

        # 4. Instruction / Project Memory Profile
        mem_chars = len(instruction_memory or "")
        mem_tokens = max(0, mem_chars // 4)
        if mem_tokens > 0:
            components.append(
                ContextComponentProfile(
                    kind=ContextComponentKind.INSTRUCTION_MEMORY,
                    name="Project Memory & Instructions",
                    character_count=mem_chars,
                    estimated_tokens=mem_tokens,
                    percentage=0.0,
                )
            )

        total_tokens = sum(c.estimated_tokens for c in components)
        # Calculate dynamic percentages
        normalized_components: list[ContextComponentProfile] = []
        for c in components:
            pct = (c.estimated_tokens / total_tokens * 100.0) if total_tokens > 0 else 0.0
            normalized_components.append(
                ContextComponentProfile(
                    kind=c.kind,
                    name=c.name,
                    character_count=c.character_count,
                    estimated_tokens=c.estimated_tokens,
                    percentage=round(pct, 1),
                    details=c.details,
                )
            )

        # 5. Diagnostic Warnings and Dynamic Sleep Suggestions
        warnings: list[str] = []
        suggested_sleep: list[str] = []

        mcp_ratio = mcp_tokens / total_tokens if total_tokens > 0 else 0.0
        if mcp_tokens >= self.mcp_warning_token_threshold or mcp_ratio >= self.mcp_warning_ratio_threshold:
            warnings.append(
                f"External MCP schemas consume {mcp_tokens} tokens ({mcp_ratio * 100:.1f}% of cold context). "
                "Consider hibernating idle integrations to improve latency and reduce cost."
            )

        # Heuristic for recommending sleep on non-local servers (e.g. Jira, Figma, Slack)
        for s in active_mcp:
            lower_tags = [t.lower() for t in s.tags]
            lower_id = s.server_id.lower()
            if any(t in lower_tags for t in ["collaboration", "design", "crm", "remote"]) or any(
                n in lower_id for n in ["jira", "figma", "slack", "salesforce"]
            ):
                suggested_sleep.append(s.server_id)

        return ColdStartContextProfile(
            session_id=session_id,
            total_estimated_tokens=total_tokens,
            components=normalized_components,
            mounted_mcp_servers=raw_mcp_list,
            warnings=warnings,
            suggested_mcp_sleep=suggested_sleep,
        )

    def render_profile_tree(self, profile: ColdStartContextProfile) -> str:
        """Render a tree-formatted summary similar to Claude Code's /context command."""
        lines: list[str] = [
            f"📊 **Session Cold-Start Context Profile** (Total: {profile.total_estimated_tokens:,} tokens):",
        ]
        for comp in profile.components:
            bar_len = int(comp.percentage / 5)
            progress_bar = "█" * bar_len + "░" * (20 - bar_len)
            detail_str = ""
            if comp.details:
                detail_str = f" ({', '.join(f'{k}: {v}' for k, v in comp.details.items())})"
            lines.append(
                f"  ├─ {comp.name:<28} : {comp.estimated_tokens:>6,} tokens [{progress_bar}] {comp.percentage:>5.1f}%{detail_str}"
            )

        if profile.warnings:
            lines.append("  ⚠️ **Diagnostics & Recommendations**:")
            for w in profile.warnings:
                lines.append(f"     * {w}")

        if profile.suggested_mcp_sleep:
            lines.append(f"     * Suggested MCP sleep: {', '.join(profile.suggested_mcp_sleep)}")

        return "\n".join(lines)
