"""Forget raw evidence and re-anchor dependent compiled pages.

[POS]
See module docstring.
"""

from __future__ import annotations

from dataclasses import dataclass

from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure
from myrm_agent_harness.toolkits.wiki.pipeline.cognitive_map.events import (
    WikiMapEvent,
    WikiMapEventType,
)
from myrm_agent_harness.toolkits.wiki.pipeline.cognitive_map.writer import (
    append_log_entry,
)
from myrm_agent_harness.toolkits.wiki.pipeline.raw_gate.errors import RawGateError
from myrm_agent_harness.toolkits.wiki.pipeline.raw_gate.evidence_removal import (
    remove_raw_evidence,
)
from myrm_agent_harness.toolkits.wiki.pipeline.raw_gate.security_hook import (
    apply_raw_security_scan,
)
from myrm_agent_harness.toolkits.wiki.pipeline.raw_gate.types import RawGateCaller


@dataclass(frozen=True, slots=True)
class ForgetEvidenceResult:
    relative_path: str
    deleted: bool
    content_hash: str
    affected_concepts: tuple[str, ...]
    republished_concepts: tuple[str, ...]


async def forget_evidence(
    structure: WikiStructure,
    relative_path: str,
    *,
    reason: str,
    caller: RawGateCaller,
    compiler: object | None = None,
    indexer: object | None = None,
) -> ForgetEvidenceResult:
    """Delete a raw file and rescan/republish concepts that referenced it."""
    result = await remove_raw_evidence(
        structure,
        relative_path,
        reason=reason,
        caller=caller,
        delete_file=True,
        compiler=compiler,
        indexer=indexer,
    )
    return ForgetEvidenceResult(
        relative_path=result.relative_path,
        deleted=result.deleted,
        content_hash=result.content_hash,
        affected_concepts=result.affected_concepts,
        republished_concepts=result.republished_concepts,
    )


async def scan_existing_raw_vault(
    structure: WikiStructure,
    indexer: object | None = None,
) -> dict[str, object]:
    """Scan all existing raw files; redact in place or remove blocked content."""
    scanned = 0
    redacted = 0
    removed = 0
    paths_redacted: list[str] = []
    paths_removed: list[str] = []

    remove_raw_index = getattr(indexer, "remove_raw_text_index", None)

    for raw_path in structure.list_raw_files("*"):
        if not raw_path.is_file():
            continue
        scanned += 1
        rel = raw_path.relative_to(structure.raw_dir).as_posix()
        original = raw_path.read_text(encoding="utf-8")
        try:
            cleaned = apply_raw_security_scan(
                structure,
                relative_path=rel,
                content=original,
                caller="settings",
            )
        except RawGateError:
            removed += 1
            paths_removed.append(rel)
            append_log_entry(
                structure,
                WikiMapEvent(
                    event_type=WikiMapEventType.RAW_SECURITY,
                    summary=f"Removed blocked raw source: {rel}",
                    details={
                        "caller": "settings",
                        "path": rel,
                        "action": "removed",
                        "reason": "credential_unredactable",
                    },
                ),
            )
            raw_path.unlink(missing_ok=True)
            if callable(remove_raw_index):
                remove_raw_index(raw_path.stem)
            continue
        if cleaned != original:
            raw_path.write_text(cleaned, encoding="utf-8")
            redacted += 1
            paths_redacted.append(rel)

    return {
        "files_scanned": scanned,
        "files_redacted": redacted,
        "files_blocked": removed,
        "files_removed": removed,
        "redacted_paths": paths_redacted,
        "removed_paths": paths_removed,
    }
