"""Loader discovering system append and replace directive files across workspace and user home.

[INPUT]
- agent.context_management.system_append_channel.system_append_types::AppendPromptSource, PromptChannelKind
  (POS: Types and models for system prompt strong append channel suite.)

[OUTPUT]
- SystemPromptAppendLoader: Discovers and parses append-system.md and SYSTEM.md directive files.

[POS]
Loader discovering system append and replace directive files across workspace and user home.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .system_append_types import AppendPromptSource, PromptChannelKind


class SystemPromptAppendLoader:
    """Discovers and parses append-system.md and SYSTEM.md directive files."""

    APPEND_CANDIDATES: List[str] = [
        ".myrm/append-system.md",
        "append-system.md",
    ]
    GLOBAL_APPEND_CANDIDATES: List[str] = [
        "~/.myrm/agent/append-system.md",
        "~/.pi/agent/append-system.md",
    ]
    REPLACE_CANDIDATES: List[str] = [
        ".myrm/SYSTEM.md",
        "SYSTEM.md",
    ]

    def __init__(self, mock_vfs: Optional[Dict[str, str]] = None) -> None:
        self._mock_vfs = mock_vfs

    def _read_content(self, path_str: str) -> Optional[str]:
        if self._mock_vfs is not None:
            return self._mock_vfs.get(path_str)
        try:
            expanded = Path(os.path.expanduser(path_str))
            if expanded.is_file():
                return expanded.read_text(encoding="utf-8")
        except Exception:
            return None
        return None

    def discover_sources(
        self,
        workspace_root: str,
        allow_full_replace: bool = False,
    ) -> Tuple[List[AppendPromptSource], Optional[AppendPromptSource]]:
        """Discover append directives and optional full replace directive.

        Returns:
            Tuple of (list of append sources, optional single replace source if allowed and present).
        """
        append_sources: List[AppendPromptSource] = []
        replace_source: Optional[AppendPromptSource] = None

        # 1. Check user-level global append candidates
        for glob_path in self.GLOBAL_APPEND_CANDIDATES:
            content = self._read_content(glob_path)
            if content is not None and content.strip():
                digest = hashlib.sha256(content.encode("utf-8")).hexdigest()[:12]
                append_sources.append(
                    AppendPromptSource(
                        source_path=glob_path,
                        channel_kind=PromptChannelKind.STRONG_APPEND_SYSTEM,
                        content=content.strip(),
                        digest=digest,
                        priority=80,  # Global runs first
                    )
                )
                break  # Only highest priority global is picked

        # 2. Check workspace-level append candidates
        for ws_rel in self.APPEND_CANDIDATES:
            ws_path = str(Path(workspace_root) / ws_rel)
            content = self._read_content(ws_path)
            if content is not None and content.strip():
                digest = hashlib.sha256(content.encode("utf-8")).hexdigest()[:12]
                append_sources.append(
                    AppendPromptSource(
                        source_path=ws_path,
                        channel_kind=PromptChannelKind.STRONG_APPEND_SYSTEM,
                        content=content.strip(),
                        digest=digest,
                        priority=100,  # Workspace has higher precedence
                    )
                )
                break

        # 3. Check full replacement SYSTEM.md only if explicitly enabled
        if allow_full_replace:
            for rep_rel in self.REPLACE_CANDIDATES:
                rep_path = str(Path(workspace_root) / rep_rel)
                content = self._read_content(rep_path)
                if content is not None and content.strip():
                    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()[:12]
                    replace_source = AppendPromptSource(
                        source_path=rep_path,
                        channel_kind=PromptChannelKind.FULL_REPLACE_SYSTEM,
                        content=content.strip(),
                        digest=digest,
                        priority=200,
                    )
                    break

        return append_sources, replace_source
