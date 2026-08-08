"""Vault markdown write guard — preserve YAML frontmatter on in-place edits.

[INPUT]
- file_ops write/edit pre and post content
- vault_scope.is_vault_markdown_path

[OUTPUT]
- MarkdownVaultWriteGuard.apply: adjusted content + user-facing warnings

[POS]
Post-planning, pre-write guard for Obsidian vault notes. Zero LLM tools.
"""

from __future__ import annotations

from myrm_agent_harness.agent.meta_tools.file_ops.utils.markdown_frontmatter import (
    preserve_frontmatter_on_edit,
)

from ..utils.vault_scope import is_vault_markdown_path


class MarkdownVaultWriteGuard:
    """Apply vault markdown write invariants before persisting content."""

    @staticmethod
    def apply(
        path: str,
        pre_content: str | None,
        post_content: str,
    ) -> tuple[str, list[str]]:
        """Return content safe to write and optional warnings for tool output."""
        if pre_content is None or not is_vault_markdown_path(path):
            return post_content, []

        merged, warnings = preserve_frontmatter_on_edit(pre_content, post_content)
        return merged, warnings
