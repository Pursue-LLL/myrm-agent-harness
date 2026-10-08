"""Expanded 1,200-word dialogue skeleton anchor builder for high-fidelity cross-session handoffs.

[INPUT]
- HistoricalSessionTurn: Sequence of turns from origin session.
- ExpandedHandoffConfig: Configuration governing word budgets and character limits.
- ExpandedHandoffAnchor: Constructed anchor data model.

[OUTPUT]
- ExpandedSkeletonAnchorBuilder: Synthesizes rich 1,200-word context skeleton preserving decisions, paths, and rejected ideas.

[POS]
Builder layer in expanded handoff pipeline converting full turn transcripts into rich anchor skeletons.
"""

from __future__ import annotations

import re
import time
from typing import Sequence

from .handoff_types import (
    ExpandedHandoffAnchor,
    ExpandedHandoffConfig,
    HistoricalSessionTurn,
)


class ExpandedSkeletonAnchorBuilder:
    """Constructs a comprehensive 1,200-word expanded context anchor spanning cross-session boundaries."""

    # Heuristic extractors for technical anchors and rejected alternatives
    REJECTED_PATH_PATTERNS: tuple[re.Pattern[str], ...] = (
        re.compile(r"(?:reject|abandon|rule out|disregard|failed attempt|deprecated|不采用|放弃|否决)[^.\n]+", re.IGNORECASE),
        re.compile(r"(?:instead of|rather than|alternatively)[^.\n]+", re.IGNORECASE),
    )

    CONSTRAINT_PATTERNS: tuple[re.Pattern[str], ...] = (
        re.compile(r"(?:must|never|always|strictly|cannot|mandatory|必须|严禁|绝不能)[^.\n]+", re.IGNORECASE),
    )

    ASSET_PATTERNS: tuple[re.Pattern[str], ...] = (
        re.compile(r"([a-zA-Z0-9_\-\./]+\.(?:py|ts|tsx|js|json|md|rs|go|sh|toml|yaml|yml)(?::\d+)?)"),
        re.compile(r"(\b[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}\b)", re.IGNORECASE),
    )

    def __init__(self, config: ExpandedHandoffConfig | None = None) -> None:
        self._config = config or ExpandedHandoffConfig()

    def _extract_items(
        self,
        turns: Sequence[HistoricalSessionTurn],
        patterns: Sequence[re.Pattern[str]],
        max_items: int = 5,
    ) -> tuple[str, ...]:
        """Extract matching snippets across turns while preserving uniqueness."""
        found: list[str] = []
        for t in turns:
            for pat in patterns:
                for match in pat.finditer(t.content):
                    snippet = match.group(0).strip()
                    if snippet and snippet not in found:
                        found.append(snippet)
                        if len(found) >= max_items:
                            return tuple(found)
        return tuple(found)

    def build_anchor(
        self,
        origin_session_id: str,
        target_session_id: str,
        turns: Sequence[HistoricalSessionTurn],
        title: str = "",
    ) -> ExpandedHandoffAnchor:
        """Synthesize turns into a rich 1,200-word expanded context anchor."""
        if not turns:
            empty_text = "No prior dialogue turns available for cross-session handoff."
            return ExpandedHandoffAnchor(
                origin_session_id=origin_session_id,
                target_session_id=target_session_id,
                anchor_title=title or "Empty Handoff",
                expanded_skeleton_text=empty_text,
                word_count=len(empty_text.split()),
                created_at=time.time(),
                origin_total_turns=0,
                search_pointer_key=f"archive:{origin_session_id}",
            )

        anchor_name = title or f"Session Handoff from #{origin_session_id[:8]}"
        constraints = self._extract_items(turns, self.CONSTRAINT_PATTERNS, max_items=6)
        rejected = self._extract_items(turns, self.REJECTED_PATH_PATTERNS, max_items=4)
        assets = self._extract_items(turns, self.ASSET_PATTERNS, max_items=10)

        # Assemble rich structured Markdown sections
        sections: list[str] = [
            f"# [Cross-Session Expanded Dialogue Anchor: {anchor_name}]",
            f"> Origin Session: `{origin_session_id}` | Recorded Turns: {len(turns)}",
            "",
            "## 1. Core Mission & Critical Constraints",
        ]

        if constraints:
            for c in constraints:
                sections.append(f"- ⚠️ {c}")
        else:
            first_user_turn = next((t.content.strip() for t in turns if t.role == "user"), "General Task")
            sections.append(f"- Primary Objective: {first_user_turn[:200]}")

        sections.extend([
            "",
            "## 2. Architectural Decisions & Deprecated Paths",
        ])
        if rejected:
            for r in rejected:
                sections.append(f"- ❌ Rejected Alternative: {r}")
        else:
            sections.append("- All explored technical directions remain aligned with current target.")

        sections.extend([
            "",
            "## 3. Key Technical Assets & Anchors",
        ])
        if assets:
            for a in assets:
                sections.append(f"- 📦 `{a}`")
        else:
            sections.append("- Standard workspace modules active.")

        # Section 4: Chronological Milestones (capturing last 6 significant turns)
        sections.extend([
            "",
            "## 4. Chronological Trajectory & Active Breakpoint",
        ])
        recent_turns = turns[-6:] if len(turns) >= 6 else turns
        for idx, t in enumerate(recent_turns, 1):
            clean_content = t.content.strip().replace("\n", " ")
            if len(clean_content) > 280:
                clean_content = clean_content[:280] + "..."
            sections.append(f"- **Turn {t.turn_id} ({t.role.upper()})**: {clean_content}")

        raw_text = "\n".join(sections).strip()

        # Enforce character budget
        if len(raw_text) > self._config.max_char_budget:
            raw_text = raw_text[: self._config.max_char_budget] + "\n...[Remainder indexed in archive]"

        words = len(raw_text.split())

        return ExpandedHandoffAnchor(
            origin_session_id=origin_session_id,
            target_session_id=target_session_id,
            anchor_title=anchor_name,
            expanded_skeleton_text=raw_text,
            word_count=words,
            created_at=time.time(),
            origin_total_turns=len(turns),
            search_pointer_key=f"archive:{origin_session_id}",
        )
