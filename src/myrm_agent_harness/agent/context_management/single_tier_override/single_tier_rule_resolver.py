"""Resolver scanning workspace directories and enforcing single-tier rule override semantics."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .single_tier_override_types import (
    OverrideResolutionKind,
    SingleTierRuleAssemblyReceipt,
    WorkspaceRuleFileEntry,
)


class SingleTierRuleResolver:
    """Scans and resolves hierarchical workspace rules with single-tier override semantics."""

    OVERRIDE_FILENAMES: List[str] = ["AGENTS.override.md", ".myrm.override.md"]
    DEFAULT_FILENAMES: List[str] = ["AGENTS.md", ".myrm.md", "RULES.md"]

    def __init__(self, file_reader_mock: Optional[Dict[str, str]] = None) -> None:
        # file_reader_mock facilitates testing without touching physical filesystem
        self._mock_vfs = file_reader_mock

    def _read_file_content(self, path_str: str) -> Optional[str]:
        if self._mock_vfs is not None:
            return self._mock_vfs.get(path_str)
        p = Path(path_str)
        if p.is_file():
            try:
                return p.read_text(encoding="utf-8")
            except Exception:
                return None
        return None

    def _find_dir_rule(self, dir_path: str) -> Tuple[Optional[WorkspaceRuleFileEntry], List[str]]:
        """Check a single directory for override or default rule files."""
        # 1. Check override files first
        for ov_name in self.OVERRIDE_FILENAMES:
            candidate_path = str(Path(dir_path) / ov_name)
            content = self._read_file_content(candidate_path)
            if content is not None:
                digest = hashlib.sha256(content.encode("utf-8")).hexdigest()[:12]
                entry = WorkspaceRuleFileEntry(
                    file_path=candidate_path,
                    dir_path=dir_path,
                    file_name=ov_name,
                    is_override=True,
                    content=content,
                    content_digest=digest,
                )
                # Any default files in the same directory are suppressed
                suppressed: List[str] = []
                for def_name in self.DEFAULT_FILENAMES:
                    def_path = str(Path(dir_path) / def_name)
                    if self._read_file_content(def_path) is not None:
                        suppressed.append(def_path)
                return entry, suppressed

        # 2. Check default files if no override
        for def_name in self.DEFAULT_FILENAMES:
            candidate_path = str(Path(dir_path) / def_name)
            content = self._read_file_content(candidate_path)
            if content is not None:
                digest = hashlib.sha256(content.encode("utf-8")).hexdigest()[:12]
                entry = WorkspaceRuleFileEntry(
                    file_path=candidate_path,
                    dir_path=dir_path,
                    file_name=def_name,
                    is_override=False,
                    content=content,
                    content_digest=digest,
                )
                return entry, []

        return None, []

    def resolve_hierarchy(
        self,
        target_dir: str,
        workspace_root: str,
        opt_out_context_files: bool = False,
    ) -> SingleTierRuleAssemblyReceipt:
        """Resolve ascending directory chain from target_dir up to workspace_root."""
        if opt_out_context_files:
            return SingleTierRuleAssemblyReceipt(
                target_dir=target_dir,
                workspace_root=workspace_root,
                resolution=OverrideResolutionKind.OPT_OUT_DISABLED,
                effective_rule_chain=[],
                suppressed_default_files=[],
                combined_prompt_content="",
                assembly_hash="opt-out",
            )

        norm_target = str(Path(target_dir).resolve()) if self._mock_vfs is None else target_dir
        norm_root = str(Path(workspace_root).resolve()) if self._mock_vfs is None else workspace_root

        # Build ascending chain from target_dir to root
        chain_dirs: List[str] = []
        curr = norm_target
        while True:
            chain_dirs.append(curr)
            if curr == norm_root or curr == "/" or curr == Path(curr).parent.as_posix():
                break
            parent = str(Path(curr).parent)
            if parent == curr:
                break
            curr = parent

        # To maintain parent-first inheritance, reverse chain (root -> ... -> target_dir)
        reversed_dirs = list(reversed(chain_dirs))

        effective_entries: List[WorkspaceRuleFileEntry] = []
        all_suppressed: List[str] = []
        overridden_detected = False

        for d in reversed_dirs:
            entry, suppressed = self._find_dir_rule(d)
            if entry is not None:
                effective_entries.append(entry)
                if entry.is_override:
                    overridden_detected = True
            all_suppressed.extend(suppressed)

        resolution = (
            OverrideResolutionKind.SINGLE_TIER_OVERRIDDEN
            if overridden_detected
            else OverrideResolutionKind.FALLTHROUGH_STANDARD
        )

        # Assemble prompt text
        prompt_chunks: List[str] = []
        for e in effective_entries:
            tag = "OVERRIDE" if e.is_override else "RULE"
            prompt_chunks.append(f"<!-- [{tag}] Source: {e.file_path} -->\n{e.content.strip()}")

        combined_text = "\n\n".join(prompt_chunks)
        assembly_hash = hashlib.sha256(combined_text.encode("utf-8")).hexdigest()[:16]

        return SingleTierRuleAssemblyReceipt(
            target_dir=norm_target,
            workspace_root=norm_root,
            resolution=resolution,
            effective_rule_chain=effective_entries,
            suppressed_default_files=all_suppressed,
            combined_prompt_content=combined_text,
            assembly_hash=assembly_hash,
        )
