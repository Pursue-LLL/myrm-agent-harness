"""Resume configuration consistency validator.

Verifies that the current Agent config matches the config saved in the
checkpoint before resuming, preventing prompt cache invalidation from
config drift.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from myrm_agent_harness.utils.logger_utils import get_agent_logger

if TYPE_CHECKING:
    pass

logger = get_agent_logger(__name__)


class ResumeValidator:
    """Resume configuration consistency validator.

    Verifies that the current Agent config matches the checkpoint config,
    preventing prompt cache invalidation from config drift.
    """

    def validate(self, checkpoint_config: dict[str, object], current_config: dict[str, object]) -> list[str]:
        """Validate configuration consistency.

        Args:
            checkpoint_config: Config saved in the checkpoint.
            current_config: Current Agent config.

        Returns:
            List of inconsistent config items (empty if consistent).
        """
        issues: list[str] = []

        checkpoint_agent_id = checkpoint_config.get("agent_id")
        current_agent_id = current_config.get("agent_id")
        if checkpoint_agent_id and current_agent_id and checkpoint_agent_id != current_agent_id:
            issues.append(f"agent_id_mismatch: {checkpoint_agent_id} -> {current_agent_id}")
            logger.error("[ResumeValidator] Agent ID mismatch: %s -> %s", checkpoint_agent_id, current_agent_id)

        checkpoint_prompt = checkpoint_config.get("system_prompt")
        current_prompt = current_config.get("system_prompt")
        if checkpoint_prompt and current_prompt and checkpoint_prompt != current_prompt:
            issues.append("system_prompt_changed")
            logger.warning(
                "[ResumeValidator] System prompt changed (length: %d -> %d)",
                len(str(checkpoint_prompt)),
                len(str(current_prompt)),
            )

        checkpoint_tools = checkpoint_config.get("tools")
        current_tools = current_config.get("tools")
        if checkpoint_tools and current_tools:
            checkpoint_tool_names = self._extract_tool_names(checkpoint_tools)
            current_tool_names = self._extract_tool_names(current_tools)
            if checkpoint_tool_names != current_tool_names:
                added = current_tool_names - checkpoint_tool_names
                removed = checkpoint_tool_names - current_tool_names
                issues.append(f"tools_changed: +{len(added)} -{len(removed)}")
                logger.warning(
                    "[ResumeValidator] Tools changed (added: %s, removed: %s)",
                    list(added)[:3],
                    list(removed)[:3],
                )

        return issues

    def _extract_tool_names(self, tools: object) -> set[str]:
        """Extract tool names from tools configuration.

        Args:
            tools: Tools config (may be list or other format).

        Returns:
            Set of tool names.
        """
        if not isinstance(tools, list):
            return set()

        names: set[str] = set()
        for tool in tools:
            if isinstance(tool, dict) and "name" in tool:
                names.add(str(tool["name"]))
            elif hasattr(tool, "name"):
                names.add(str(tool.name))
        return names

    def generate_diff_report(self, checkpoint_config: dict[str, object], current_config: dict[str, object]) -> str:
        """Generate a detailed config diff report.

        Args:
            checkpoint_config: Config saved in the checkpoint.
            current_config: Current Agent config.

        Returns:
            Detailed config diff report in Markdown format.
        """
        issues = self.validate(checkpoint_config, current_config)

        if not issues:
            return "[OK] Config consistent, no changes."

        report_lines = ["## Resume Config Diff Report\n"]

        checkpoint_agent_id = checkpoint_config.get("agent_id")
        current_agent_id = current_config.get("agent_id")
        if checkpoint_agent_id != current_agent_id:
            report_lines.append("### Agent ID\n")
            report_lines.append(f"- Checkpoint: `{checkpoint_agent_id}`\n")
            report_lines.append(f"- Current: `{current_agent_id}`\n")

        checkpoint_prompt = checkpoint_config.get("system_prompt")
        current_prompt = current_config.get("system_prompt")
        if checkpoint_prompt and current_prompt and checkpoint_prompt != current_prompt:
            report_lines.append("### System Prompt\n")
            report_lines.append(f"- Checkpoint: {len(str(checkpoint_prompt))} chars\n")
            report_lines.append(f"- Current: {len(str(current_prompt))} chars\n")
            similarity = self._calculate_similarity(str(checkpoint_prompt), str(current_prompt))
            report_lines.append(f"- Similarity: {similarity:.1f}%\n")

        checkpoint_tools = checkpoint_config.get("tools")
        current_tools = current_config.get("tools")
        if checkpoint_tools and current_tools:
            checkpoint_tool_names = self._extract_tool_names(checkpoint_tools)
            current_tool_names = self._extract_tool_names(current_tools)
            if checkpoint_tool_names != current_tool_names:
                added = current_tool_names - checkpoint_tool_names
                removed = checkpoint_tool_names - current_tool_names
                report_lines.append("### Tools\n")
                if added:
                    report_lines.append(f"- Added ({len(added)}): {', '.join(sorted(added))}\n")
                if removed:
                    report_lines.append(f"- Removed ({len(removed)}): {', '.join(sorted(removed))}\n")

        return "".join(report_lines)

    def _calculate_similarity(self, text1: str, text2: str) -> float:
        """Calculate character-level text similarity.

        Args:
            text1: First text.
            text2: Second text.

        Returns:
            Similarity percentage (0-100).
        """
        if text1 == text2:
            return 100.0
        if not text1 or not text2:
            return 0.0

        # 简单的字符级相似度（Levenshtein距离的简化版）
        max_len = max(len(text1), len(text2))
        common_len = sum(1 for c1, c2 in zip(text1, text2, strict=False) if c1 == c2)
        return (common_len / max_len) * 100.0
