"""Wiki vault portability — archive export without product-specific UI.

[INPUT]
- .obsidian_canvas::extract_canvas_text_nodes, extract_wikilinks_from_markdown (POS: Obsidian canvas/markdown text parsing)
- .obsidian_tools::create_obsidian_tools (POS: Obsidian agent tools)
- .vault_archive::build_vault_archive_zip (POS: deterministic vault ZIP packager)
- .vault_git::commit_vault_git_snapshot (POS: local git snapshot automation)

[OUTPUT]
- build_vault_archive_zip, commit_vault_git_snapshot, create_obsidian_tools, extract_canvas_text_nodes

[POS]
Wiki 导出与可移植性入口包。聚合导出本地 Git 快照、Obsidian 工具与 Vault ZIP 打包能力。
"""

from .obsidian_canvas import (
    CanvasTextNode,
    WikilinkReference,
    extract_canvas_text_nodes,
    extract_wikilinks_from_markdown,
    resolve_one_hop_wikilinks,
)
from .obsidian_tools import create_obsidian_tools
from .vault_archive import EXPORT_MANIFEST_VERSION, build_vault_archive_zip
from .vault_git import VaultGitCommitResult, commit_vault_git_snapshot, maybe_commit_vault_git_snapshot

__all__ = [
    "CanvasTextNode",
    "EXPORT_MANIFEST_VERSION",
    "VaultGitCommitResult",
    "WikilinkReference",
    "build_vault_archive_zip",
    "commit_vault_git_snapshot",
    "create_obsidian_tools",
    "extract_canvas_text_nodes",
    "extract_wikilinks_from_markdown",
    "maybe_commit_vault_git_snapshot",
    "resolve_one_hop_wikilinks",
]
