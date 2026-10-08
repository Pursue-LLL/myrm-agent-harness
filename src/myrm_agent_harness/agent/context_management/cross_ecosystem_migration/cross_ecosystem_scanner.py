"""Scanner discovering foreign and standard agent rule files across ecosystems."""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
from typing import Dict, List, Optional

from .cross_ecosystem_types import (
    DiscoveredEcosystemFile,
    EcosystemSpecKind,
    RuleSectionCategory,
)


class CrossEcosystemRuleScanner:
    """Discovers foreign and standard rule files from Claude, Cursor, Copilot, Windsurf, and Agentic AI."""

    CANDIDATE_PATTERNS: List[tuple[str, EcosystemSpecKind]] = [
        ("AGENTS.md", EcosystemSpecKind.AGENTIC_AI_FOUNDATION),
        ("CLAUDE.md", EcosystemSpecKind.CLAUDE_CODE),
        (".cursorrules", EcosystemSpecKind.CURSOR_RULES),
        (".github/copilot-instructions.md", EcosystemSpecKind.COPILOT_INSTRUCTIONS),
        (".windsurfrules", EcosystemSpecKind.WINDSURF_RULES),
    ]

    def __init__(self, mock_vfs: Optional[Dict[str, str]] = None) -> None:
        self._mock_vfs = mock_vfs

    def _read_file(self, path_str: str) -> Optional[str]:
        if self._mock_vfs is not None:
            return self._mock_vfs.get(path_str)
        try:
            p = Path(path_str)
            if p.is_file():
                return p.read_text(encoding="utf-8")
        except Exception:
            return None
        return None

    def _extract_sections(self, content: str) -> Dict[RuleSectionCategory, str]:
        """Categorize rule markdown content into semantic categories."""
        sections: Dict[RuleSectionCategory, str] = {}
        lines = content.splitlines()

        current_category = RuleSectionCategory.PROJECT_OVERVIEW
        buffer: List[str] = []

        for line in lines:
            lower = line.lower()
            if re.match(r"^#{1,3}\s+", line):
                # Save previous buffer
                if buffer:
                    sections[current_category] = "\n".join(buffer).strip()
                    buffer = []

                if any(w in lower for w in ["build", "test", "run", "command"]):
                    current_category = RuleSectionCategory.BUILD_AND_TEST
                elif any(w in lower for w in ["style", "lint", "convention", "format", "code"]):
                    current_category = RuleSectionCategory.CODE_STYLE
                elif any(w in lower for w in ["restrict", "prohibit", "guard", "security", "never"]):
                    current_category = RuleSectionCategory.RESTRICTIONS_GUARD
                elif any(w in lower for w in ["overview", "project", "about"]):
                    current_category = RuleSectionCategory.PROJECT_OVERVIEW
                else:
                    current_category = RuleSectionCategory.CUSTOM_DIRECTIVE

            buffer.append(line)

        if buffer:
            sections[current_category] = "\n".join(buffer).strip()

        return sections

    def scan_workspace(self, workspace_root: str) -> List[DiscoveredEcosystemFile]:
        """Scan workspace for all recognized rule files and parse their contents."""
        discovered: List[DiscoveredEcosystemFile] = []

        # 1. Check fixed filename patterns
        for rel_path, eco_kind in self.CANDIDATE_PATTERNS:
            full_path = str(Path(workspace_root) / rel_path)
            content = self._read_file(full_path)
            if content is not None and content.strip():
                digest = hashlib.sha256(content.encode("utf-8")).hexdigest()[:12]
                sections = self._extract_sections(content)
                discovered.append(
                    DiscoveredEcosystemFile(
                        file_path=full_path,
                        ecosystem=eco_kind,
                        content=content.strip(),
                        digest=digest,
                        parsed_sections=sections,
                    )
                )

        # 2. Check .cursor/rules/*.mdc pattern
        if self._mock_vfs is not None:
            for k, v in self._mock_vfs.items():
                if k.startswith(f"{workspace_root}/.cursor/rules/") and k.endswith(".mdc"):
                    digest = hashlib.sha256(v.encode("utf-8")).hexdigest()[:12]
                    discovered.append(
                        DiscoveredEcosystemFile(
                            file_path=k,
                            ecosystem=EcosystemSpecKind.CURSOR_MDC,
                            content=v.strip(),
                            digest=digest,
                            parsed_sections=self._extract_sections(v),
                        )
                    )
        else:
            rules_dir = Path(workspace_root) / ".cursor" / "rules"
            if rules_dir.is_dir():
                for mdc_file in rules_dir.glob("*.mdc"):
                    text = self._read_file(str(mdc_file))
                    if text:
                        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
                        discovered.append(
                            DiscoveredEcosystemFile(
                                file_path=str(mdc_file),
                                ecosystem=EcosystemSpecKind.CURSOR_MDC,
                                content=text.strip(),
                                digest=digest,
                                parsed_sections=self._extract_sections(text),
                            )
                        )

        return discovered
