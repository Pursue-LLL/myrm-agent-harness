"""Architecture Decision Record (ADR) discovery and MADR status filtering.

Scans the workspace directory for living architectural decision records
(e.g., docs/decisions/*.md, doc/decisions/*.md) and loads accepted decisions
while filtering out deprecated, superseded, or rejected records.

[INPUT]
- pathlib::Path (POS: Python filesystem path standard library)
- agent.workspace_rules.scanner::RuleFile, _load_rule_file, _inode_key (POS: Workspace rule file models and low-level inode loading)

[OUTPUT]
- scan_adr_rules(): Discover and filter accepted ADR files, returns list[RuleFile]
- parse_adr_status(): Extract decision status string from ADR content

[POS]
Living architecture decision record scanner. Enforces MADR / Nygard specification
filtering to keep Agent workspace context focused strictly on active, accepted decisions.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from myrm_agent_harness.agent.workspace_rules.scanner import RuleFile

logger = logging.getLogger(__name__)

_ADR_SUBDIRS: tuple[str, ...] = (
    "docs/decisions",
    "doc/decisions",
    ".myrm/decisions",
)

# Active status keywords that qualify an ADR for context injection
_ACCEPTED_STATUSES: frozenset[str] = frozenset(
    {"accepted", "approved", "active", "adopted", "valid"}
)

# Inactive status keywords to explicitly reject
_INACTIVE_STATUSES: frozenset[str] = frozenset(
    {"deprecated", "superseded", "rejected", "proposed", "draft", "abandoned"}
)

_STATUS_LINE_RE = re.compile(
    r"^\s*(?:[\*\-]\s+)?(?:\*\*)?status(?::\*\*|\*\*:|:)\s*[\"'\[]?([a-zA-Z_\-]+)[\"'\]]?",
    re.IGNORECASE | re.MULTILINE,
)


def parse_adr_status(content: str) -> str:
    """Extract normalized status keyword from ADR content.

    Inspects markdown lists (* Status: accepted, **Status:** accepted), bracketed statuses,
    and YAML frontmatter (status: accepted).
    Returns lowercased status string, or 'accepted' if no explicit status is declared.
    """
    match = _STATUS_LINE_RE.search(content)
    if match:
        return match.group(1).strip().lower()
    return "accepted"


def is_adr_active(content: str) -> bool:
    """Return True if the ADR represents an active and accepted decision."""
    status = parse_adr_status(content)
    if status in _INACTIVE_STATUSES:
        return False
    if status in _ACCEPTED_STATUSES:
        return True
    return True


def scan_adr_rules(
    directory: Path,
    seen_inodes: set[tuple[int, int]],
) -> list[RuleFile]:
    """Scan directory for MADR architectural decision records.

    Traverses known decision directories, ignores non-accepted (e.g. deprecated/superseded)
    records, and returns loaded RuleFile instances.
    """
    from myrm_agent_harness.agent.workspace_rules.scanner import (
        _inode_key,
        _load_rule_file,
    )

    results: list[RuleFile] = []

    for subdir in _ADR_SUBDIRS:
        adr_dir = directory / subdir
        if not adr_dir.is_dir():
            continue

        try:
            for adr_path in sorted(adr_dir.glob("*.md")):
                if not adr_path.is_file():
                    continue

                key = _inode_key(adr_path)
                if key in seen_inodes:
                    continue

                try:
                    raw_text = adr_path.read_text(encoding="utf-8", errors="replace")
                except OSError as exc:
                    logger.warning("Failed to inspect ADR file %s: %s", adr_path, exc)
                    continue

                if not is_adr_active(raw_text):
                    logger.debug(
                        "Skipping inactive ADR record: %s (status=%s)",
                        adr_path.name,
                        parse_adr_status(raw_text),
                    )
                    continue

                seen_inodes.add(key)
                rule = _load_rule_file(adr_path, source=f"{subdir}/{adr_path.name}")
                if rule:
                    results.append(rule)
        except OSError as exc:
            logger.warning("Failed to traverse ADR directory %s: %s", subdir, exc)

    return results
