"""Idempotent Causal Deduplication Merger for KNOWN_ISSUES.md.

[INPUT]
- pathlib::Path (POS: Python filesystem path standard library)
- toolkits.memory.workspace_living.models::KnownIssueEntry, CausalDeduplicationReport, compute_error_signature (POS: Domain contract layer for workspace living documentation synchronization)

[OUTPUT]
- CausalIssueMerger: Atomic deduplication merger ensuring zero duplicated pitfalls in KNOWN_ISSUES.md

[POS]
Concurrency-safe, idempotent file merger for living environmental known issues.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from myrm_agent_harness.toolkits.memory.workspace_living.models import (
    CausalDeduplicationReport,
    KnownIssueEntry,
    compute_error_signature,
)

logger = logging.getLogger(__name__)

_SIGNATURE_COMMENT_RE = re.compile(
    r"<!--\s*signature:\s*([a-fA-F0-9]+)\s*\|\s*occurrences:\s*(\d+)\s*-->",
)
_HEADER_RE = re.compile(r"^###\s*\[([^\]]+)\]\s*(.*)$", re.MULTILINE)
_TIMELINE_RE = re.compile(r"(\-\s*\*\*记录时间 \(Timeline\)\*\*:\s*([0-9\-]+)\s*~\s*)([0-9\-]+)")


class CausalIssueMerger:
    """Atomic deduplication merger for KNOWN_ISSUES.md."""

    def __init__(self, workspace_root: Path | str) -> None:
        self._workspace_root = Path(workspace_root)
        self._lock = asyncio.Lock()

    @property
    def issues_file_path(self) -> Path:
        """Target path for KNOWN_ISSUES.md."""
        return self._workspace_root / "KNOWN_ISSUES.md"

    async def merge_issue(
        self,
        *,
        title: str,
        symptom: str,
        trigger_condition: str,
        workaround: str,
    ) -> CausalDeduplicationReport:
        """Atomically merge or append a known issue entry, deduplicating by error signature."""
        async with self._lock:
            file_path = self.issues_file_path
            signature = compute_error_signature(symptom, trigger_condition)

            content = ""
            if file_path.is_file():
                try:
                    content = file_path.read_text(encoding="utf-8")
                except OSError as exc:
                    logger.warning("Failed to read %s: %s", file_path, exc)

            # Check if signature already exists
            sig_pattern = re.compile(
                rf"(###\s*\[([^\]]+)\][^\n]*\n)<!--\s*signature:\s*{re.escape(signature)}\s*\|\s*occurrences:\s*(\d+)\s*-->"
            )
            existing_match = sig_pattern.search(content)

            today = datetime.now(UTC).strftime("%Y-%m-%d")

            if existing_match:
                # Update existing issue idempotently
                header = existing_match.group(1)
                issue_id = existing_match.group(2)
                count = int(existing_match.group(3)) + 1

                replacement = (
                    f"{header}<!-- signature: {signature} | occurrences: {count} -->"
                )
                new_content = sig_pattern.sub(replacement, content, count=1)

                # Update the last_seen date in the Timeline field for this entry if present
                def _update_timeline(match_obj: re.Match[str]) -> str:
                    return f"{match_obj.group(1)}{today}"

                new_content = _TIMELINE_RE.sub(_update_timeline, new_content, count=1)

                self._atomic_write(file_path, new_content)
                return CausalDeduplicationReport(
                    added=False,
                    updated=True,
                    issue_id=issue_id,
                    error_signature=signature,
                    file_path=str(file_path),
                )

            # Generate next auto-increment issue ID
            existing_ids = _HEADER_RE.findall(content)
            next_idx = len(existing_ids) + 1
            issue_id = f"KI-{next_idx:03d}"

            entry = KnownIssueEntry(
                id=issue_id,
                title=title,
                symptom=symptom,
                trigger_condition=trigger_condition,
                workaround=workaround,
                error_signature=signature,
                occurred_count=1,
                first_seen=today,
                last_seen=today,
            )

            # Construct new document or append
            if not content.strip():
                new_content = (
                    "# Known Issues and Pitfalls\n\n"
                    "Living documentation of environment quirks and verified workarounds.\n\n"
                    f"{entry.to_markdown()}\n"
                )
            else:
                new_content = content.rstrip() + f"\n\n{entry.to_markdown()}\n"

            self._atomic_write(file_path, new_content)
            return CausalDeduplicationReport(
                added=True,
                updated=False,
                issue_id=issue_id,
                error_signature=signature,
                file_path=str(file_path),
            )

    @staticmethod
    def _atomic_write(target_path: Path, text: str) -> None:
        """Atomically overwrite target file using temporary file and os.replace."""
        target_path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_file = tempfile.mkstemp(
            dir=str(target_path.parent),
            prefix="known_issues_tmp_",
            suffix=".md",
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(text)
            os.replace(temp_file, str(target_path))
        except BaseException:
            if os.path.exists(temp_file):
                os.remove(temp_file)
            raise
