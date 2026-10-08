"""Multi-tier workspace rule merger abolishing legacy first-match-wins mutual exclusion.

[INPUT]
- CanonicalWorkspaceBundle: Parsed canonical files bundle.
- Path: Directory paths to scan for engineering and persona rules.

[OUTPUT]
- MergedWorkspaceContext: Harmonized multi-layer system prompt context.
- MultiTierWorkspaceMerger: Merges SOUL, AGENTS, CLAUDE, and USER files without silent discarding.

[POS]
Rule merging layer in canonical workspace protocol subsystem repairing first-match-wins bug.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

from .canonical_file_parser import CanonicalFileParser
from .canonical_types import CanonicalWorkspaceBundle


@dataclass(frozen=True)
class MergedWorkspaceContext:
    """Consolidated context containing coexisting persona and engineering rule layers."""

    system_persona_layer: str
    engineering_rules_layer: str
    user_preferences_layer: str
    tools_guidance_layer: str
    active_sources: Sequence[str] = field(default_factory=tuple)

    def render_full_system_prompt_block(self) -> str:
        """Render all layers into a coherent, non-conflicting system prompt injection."""
        blocks: list[str] = []

        if self.system_persona_layer:
            blocks.append(self.system_persona_layer)

        if self.engineering_rules_layer:
            blocks.append(f"## 🛠️ [Engineering Operating Rules & Standards]\n{self.engineering_rules_layer}")

        if self.user_preferences_layer:
            blocks.append(f"## 👤 [Active User Directives]\n{self.user_preferences_layer}")

        if self.tools_guidance_layer:
            blocks.append(f"## 🧰 [Workspace Tool Guidance]\n{self.tools_guidance_layer}")

        return "\n\n".join(blocks).strip()


class MultiTierWorkspaceMerger:
    """Harmonizes persona rules and engineering instructions into structured coexisting tiers."""

    ENGINEERING_RULE_NAMES: tuple[str, ...] = (
        "AGENTS.md",
        "agents.md",
        "CLAUDE.md",
        "claude.md",
        ".myrm.md",
        "myrm.md",
        ".cursorrules",
    )

    def __init__(self, parser: CanonicalFileParser | None = None) -> None:
        self._parser = parser or CanonicalFileParser()

    def merge_workspace(self, directory: Path) -> MergedWorkspaceContext:
        """Scan workspace and merge persona rules, engineering constraints, and user directives."""
        canonical_bundle = self._parser.parse_workspace_directory(directory)
        active_sources: list[str] = list(canonical_bundle.loaded_files)

        # 1. Assemble Persona Layer from IDENTITY and SOUL
        persona_blocks: list[str] = []
        ident = canonical_bundle.identity
        if ident.name != "Myrm" or ident.avatar_url or canonical_bundle.soul_content:
            ident_banner = f"# [Identity: {ident.emoji} {ident.name} ({ident.creature}) | Vibe: {ident.vibe}]"
            persona_blocks.append(ident_banner)

        if canonical_bundle.soul_content:
            persona_blocks.append(canonical_bundle.soul_content)

        persona_layer = "\n\n".join(persona_blocks).strip()

        # 2. Assemble Engineering Rules Layer without First-Match-Wins dropping
        engineering_blocks: list[str] = []
        for rule_name in self.ENGINEERING_RULE_NAMES:
            p = directory / rule_name
            if p.is_file():
                try:
                    content = p.read_text(encoding="utf-8").strip()
                    if content:
                        engineering_blocks.append(f"### [Source: `{rule_name}`]\n{content}")
                        active_sources.append(rule_name)
                except OSError:
                    pass

        engineering_layer = "\n\n".join(engineering_blocks).strip()

        # 3. Assemble Active User Directives Layer
        user_blocks: list[str] = []
        for d in canonical_bundle.active_user_directives:
            date_prefix = f"[{d.observed_date}] " if d.observed_date else ""
            user_blocks.append(f"- {date_prefix}{d.statement}")
        user_layer = "\n".join(user_blocks).strip()

        # 4. Tools Guidance Layer
        tools_layer = canonical_bundle.tools_guidance

        return MergedWorkspaceContext(
            system_persona_layer=persona_layer,
            engineering_rules_layer=engineering_layer,
            user_preferences_layer=user_layer,
            tools_guidance_layer=tools_layer,
            active_sources=tuple(active_sources),
        )
