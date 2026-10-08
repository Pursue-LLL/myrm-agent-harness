# [INPUT]: AgentIdentitySpec, CanonicalFileKind, CanonicalWorkspaceBundle, DirectiveStatus, UserDirectiveItem
# [OUTPUT]: CanonicalFileParser
# [POS]: agent/workspace_rules/canonical_protocol/canonical_file_parser.py

"""Parser extracting structured data from canonical workspace files (SOUL, IDENTITY, USER, BOOTSTRAP, TOOLS).

[INPUT]
- AgentIdentitySpec, CanonicalFileKind, CanonicalWorkspaceBundle, DirectiveStatus, UserDirectiveItem: Domain models.

[OUTPUT]
- CanonicalFileParser: Robust parser extracting structured identity, directives, and birth sequences.

[POS]
File parsing layer in canonical workspace protocol subsystem.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Mapping

from .canonical_types import (
    AgentIdentitySpec,
    CanonicalFileKind,
    CanonicalWorkspaceBundle,
    DirectiveStatus,
    UserDirectiveItem,
)


class CanonicalFileParser:
    """Parses standard OpenClaw / Meta Muse workspace files into structured models."""

    MAX_USER_MD_BUDGET_CHARS: int = 4000

    # Pattern for <!-- observed: 2026-09-20 | status: active/superseded -->
    DIRECTIVE_TAG_PATTERN: re.Pattern[str] = re.compile(
        r"<!--\s*observed:\s*([0-9\-_]+)\s*\|\s*status:\s*(active|superseded)\s*-->",
        re.IGNORECASE,
    )

    KV_LINE_PATTERN: re.Pattern[str] = re.compile(
        r"^\s*[-*]?\s*(?:[#*`]*)(name|creature|vibe|emoji|avatar|avatar_url)(?:[#*`]*)\s*[:=]\s*(.+)$",
        re.IGNORECASE | re.MULTILINE,
    )

    def parse_workspace_directory(self, directory: Path) -> CanonicalWorkspaceBundle:
        """Scan a directory for the 5 canonical files and produce a unified bundle."""
        loaded: list[str] = []

        # 1. Parse IDENTITY.md
        identity_path = directory / CanonicalFileKind.IDENTITY.value
        identity = AgentIdentitySpec()
        if identity_path.is_file():
            try:
                identity = self.parse_identity_content(identity_path.read_text(encoding="utf-8"))
                loaded.append(CanonicalFileKind.IDENTITY.value)
            except OSError:
                pass

        # 2. Parse SOUL.md
        soul_content = ""
        soul_path = directory / CanonicalFileKind.SOUL.value
        if soul_path.is_file():
            try:
                soul_content = soul_path.read_text(encoding="utf-8").strip()
                loaded.append(CanonicalFileKind.SOUL.value)
            except OSError:
                pass

        # 3. Parse USER.md with 4000-char budget
        active_directives: list[UserDirectiveItem] = []
        superseded_directives: list[UserDirectiveItem] = []
        user_path = directory / CanonicalFileKind.USER.value
        if user_path.is_file():
            try:
                u_text = user_path.read_text(encoding="utf-8")
                active_directives, superseded_directives = self.parse_user_directives(u_text)
                loaded.append(CanonicalFileKind.USER.value)
            except OSError:
                pass

        # 4. Parse BOOTSTRAP.md
        bootstrap_content = ""
        bootstrap_path = directory / CanonicalFileKind.BOOTSTRAP.value
        bootstrap_pending = False
        if bootstrap_path.is_file():
            try:
                bootstrap_content = bootstrap_path.read_text(encoding="utf-8").strip()
                bootstrap_pending = bool(bootstrap_content)
                loaded.append(CanonicalFileKind.BOOTSTRAP.value)
            except OSError:
                pass

        # 5. Parse TOOLS.md
        tools_guidance = ""
        tools_path = directory / CanonicalFileKind.TOOLS.value
        if tools_path.is_file():
            try:
                tools_guidance = tools_path.read_text(encoding="utf-8").strip()
                loaded.append(CanonicalFileKind.TOOLS.value)
            except OSError:
                pass

        return CanonicalWorkspaceBundle(
            identity=identity,
            soul_content=soul_content,
            active_user_directives=tuple(active_directives),
            superseded_user_directives=tuple(superseded_directives),
            tools_guidance=tools_guidance,
            bootstrap_pending=bootstrap_pending,
            bootstrap_content=bootstrap_content,
            loaded_files=tuple(loaded),
        )

    def parse_identity_content(self, text: str) -> AgentIdentitySpec:
        """Extract structured identity fields from Markdown content."""
        attrs: dict[str, str] = {}
        for match in self.KV_LINE_PATTERN.finditer(text):
            k = match.group(1).lower()
            v = match.group(2).strip().strip('"\'`')
            attrs[k] = v

        name = attrs.get("name", "Myrm")
        creature = attrs.get("creature", "Assistant")
        vibe = attrs.get("vibe", "Helpful and Direct")
        emoji = attrs.get("emoji", "🤖")
        avatar = attrs.get("avatar_url") or attrs.get("avatar", "")

        return AgentIdentitySpec(
            name=name,
            creature=creature,
            vibe=vibe,
            emoji=emoji,
            avatar_url=avatar,
            extra_attributes=attrs,
        )

    def parse_user_directives(self, text: str) -> tuple[list[UserDirectiveItem], list[UserDirectiveItem]]:
        """Parse directives from USER.md and filter by active/superseded status with budget enforcement."""
        # Enforce 4000-char budget containment
        clamped_text = text[: self.MAX_USER_MD_BUDGET_CHARS] if len(text) > self.MAX_USER_MD_BUDGET_CHARS else text

        active: list[UserDirectiveItem] = []
        superseded: list[UserDirectiveItem] = []

        lines = clamped_text.splitlines()
        current_date = ""
        current_status = DirectiveStatus.ACTIVE

        for line in lines:
            line_str = line.strip()
            if not line_str:
                continue

            # Check if this line is an annotated directive tag
            tag_match = self.DIRECTIVE_TAG_PATTERN.search(line_str)
            if tag_match:
                current_date = tag_match.group(1).strip()
                status_raw = tag_match.group(2).strip().lower()
                current_status = DirectiveStatus.SUPERSEDED if status_raw == "superseded" else DirectiveStatus.ACTIVE
                continue

            if line_str.startswith("#"):
                continue

            # If it's a bullet item or directive sentence
            if line_str.startswith(("-", "*", "•")) or len(line_str) > 15:
                clean_stmt = line_str.lstrip("-*• ").strip()
                if clean_stmt:
                    item = UserDirectiveItem(
                        statement=clean_stmt,
                        observed_date=current_date,
                        status=current_status,
                    )
                    if current_status == DirectiveStatus.ACTIVE:
                        active.append(item)
                    else:
                        superseded.append(item)
                # Reset tag state
                current_status = DirectiveStatus.ACTIVE
                current_date = ""

        return active, superseded
