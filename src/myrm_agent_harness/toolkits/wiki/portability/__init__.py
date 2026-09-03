"""Wiki vault portability — archive export without product-specific UI."""

from .obsidian_canvas import (
    CanvasTextNode,
    WikilinkReference,
    extract_canvas_text_nodes,
    extract_wikilinks_from_markdown,
    resolve_one_hop_wikilinks,
)
from .vault_archive import EXPORT_MANIFEST_VERSION, build_vault_archive_zip
from .vault_git import VaultGitCommitResult, commit_vault_git_snapshot, maybe_commit_vault_git_snapshot

__all__ = [
    "EXPORT_MANIFEST_VERSION",
    "CanvasTextNode",
    "VaultGitCommitResult",
    "WikilinkReference",
    "build_vault_archive_zip",
    "commit_vault_git_snapshot",
    "extract_canvas_text_nodes",
    "extract_wikilinks_from_markdown",
    "maybe_commit_vault_git_snapshot",
    "resolve_one_hop_wikilinks",
]
