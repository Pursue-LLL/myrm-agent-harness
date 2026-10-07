"""Parser for @-mention entities within user prompts.

[INPUT]
- agent.context_management.mention_hydration.mention_hydration_types::MentionKind (POS: Data contracts for
  zero-turn @-mention extraction, deduplication, and context injection.)

[OUTPUT]
- ParsedMention: Representation of an extracted mention target.
- parse_mentions_from_prompt: Extracts all valid file, artifact, wiki, and snippet references.

[POS]
Extracts structured @-mention entities from raw prompt text while avoiding false positives like email addresses.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Sequence

from .mention_hydration_types import MentionKind

# Regex matching explicit mentions like @file:path/a.py, @artifact:id, @wiki:topic
_EXPLICIT_MENTION_PATTERN = re.compile(
    r"(?<![\w.-])@(file|artifact|wiki|snippet):([^\s,;\"'()]+)",
    re.IGNORECASE,
)

# Regex matching implicit file mentions like @src/utils.ts, @./config.json, @models/user.py
_IMPLICIT_FILE_MENTION_PATTERN = re.compile(
    r"(?<![\w.-])@((?:[.\w\-]+/)+[.\w\-]+\.[a-zA-Z0-9_]+|[.\w\-]+\.[a-zA-Z0-9_]{1,10})",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class ParsedMention:
    """Representation of an extracted mention target."""

    raw_token: str
    kind: MentionKind
    target_path: str


def parse_mentions_from_prompt(prompt: str) -> tuple[ParsedMention, ...]:
    """Extract structured @-mention targets from raw prompt text.

    Distinguishes explicit prefixes (@file:, @artifact:) from inferred file path mentions,
    while safely disregarding email addresses (e.g. user@domain.com).
    """
    if not prompt or "@" not in prompt:
        return ()

    results: list[ParsedMention] = []
    seen_targets: set[str] = set()

    # 1. Match explicit mentions
    for match in _EXPLICIT_MENTION_PATTERN.finditer(prompt):
        kind_str = match.group(1).lower()
        target = match.group(2).strip().strip("'\"").rstrip(".,;:!?")
        raw = match.group(0)

        kind_map = {
            "file": MentionKind.FILE,
            "artifact": MentionKind.ARTIFACT,
            "wiki": MentionKind.WIKI,
            "snippet": MentionKind.SNIPPET,
        }
        kind = kind_map.get(kind_str, MentionKind.FILE)

        if target and target not in seen_targets:
            seen_targets.add(target)
            results.append(ParsedMention(raw_token=raw, kind=kind, target_path=target))

    # 2. Match implicit file mentions
    for match in _IMPLICIT_FILE_MENTION_PATTERN.finditer(prompt):
        raw = match.group(0)
        target = match.group(1).strip().strip("'\"").rstrip(".,;:!?")

        # Avoid re-adding explicit mentions already captured
        if target.startswith(("file:", "artifact:", "wiki:", "snippet:")):
            continue

        if target and target not in seen_targets:
            seen_targets.add(target)
            results.append(ParsedMention(raw_token=raw, kind=MentionKind.FILE, target_path=target))

    return tuple(results)
