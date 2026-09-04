"""Raw publication gate — single SSOT for vault raw/ writes.

[INPUT]
- ..core.structure::WikiStructure (POS: raw paths)
- ..core.canonical_registry::compute_page_lease_hash (POS: content hash)
- ..cognitive_map.writer::append_log_entry (POS: audit log)
- ..cognitive_map.events::WikiMapEvent (POS: log event types)

[OUTPUT]
- publish_raw: guarded raw file write with conflict policies

[POS]
Mirrors pipeline/apply/ for the raw evidence layer. Stable-path imports and agent
ingest route here; ephemeral timestamp paths may use FAIL or SKIP as callers choose.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from myrm_agent_harness.toolkits.wiki.core.canonical_registry import (
    compute_page_lease_hash,
)
from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure
from myrm_agent_harness.toolkits.wiki.pipeline.cognitive_map.events import (
    WikiMapEvent,
    WikiMapEventType,
)
from myrm_agent_harness.toolkits.wiki.pipeline.cognitive_map.writer import (
    append_log_entry,
)
from myrm_agent_harness.toolkits.wiki.pipeline.raw_gate.errors import RawGateError
from myrm_agent_harness.toolkits.wiki.pipeline.raw_gate.security_hook import (
    apply_raw_security_scan,
)
from myrm_agent_harness.toolkits.wiki.pipeline.raw_gate.types import (
    RawConflictPolicy,
    RawGateCaller,
    RawPublishRequest,
    RawPublishResult,
)

_VAULT_LOCKS: dict[str, asyncio.Lock] = {}


def _vault_lock(base_dir: Path) -> asyncio.Lock:
    key = str(base_dir.resolve())
    lock = _VAULT_LOCKS.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _VAULT_LOCKS[key] = lock
    return lock


_MAX_RELATIVE_PATH_LEN = 260


def _normalize_relative_path(relative_path: str) -> str:
    cleaned = relative_path.strip().replace("\\", "/").lstrip("/")
    if not cleaned:
        raise RawGateError("invalid_request", "relative_path is required")
    if len(cleaned) > _MAX_RELATIVE_PATH_LEN:
        raise RawGateError(
            "invalid_path",
            f"relative_path exceeds maximum length of {_MAX_RELATIVE_PATH_LEN}",
        )
    segments = cleaned.split("/")
    if any(seg == ".." for seg in segments):
        raise RawGateError(
            "invalid_path",
            "relative_path must not contain '..' segments",
        )
    if ":" in segments[0]:
        raise RawGateError(
            "invalid_path",
            "relative_path must be a relative path (no drive prefix)",
        )
    return cleaned


def _write_raw_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _prepare_write_content(
    structure: WikiStructure,
    *,
    relative_path: str,
    content: str,
    caller: RawGateCaller,
) -> tuple[str, bool]:
    """Security-scan content destined for raw/. Returns (cleaned_content, was_redacted)."""
    original = content
    cleaned = apply_raw_security_scan(
        structure,
        relative_path=relative_path,
        content=content,
        caller=caller,
    )
    return cleaned, cleaned != original


def _result_from_write(
    *,
    rel_path: str,
    raw_path: Path,
    content: str,
    written: bool,
    skipped: bool,
    superseded: bool,
    created: bool,
    conflict_skipped: bool,
    security_redacted: bool,
) -> RawPublishResult:
    return RawPublishResult(
        relative_path=rel_path,
        absolute_path=raw_path,
        content_hash=compute_page_lease_hash(content),
        written=written,
        skipped=skipped,
        superseded=superseded,
        created=created,
        conflict_skipped=conflict_skipped,
        security_verdict="redacted" if security_redacted else "clean",
        security_redacted=security_redacted,
        security_blocked=False,
    )


def _relative_raw_display(structure: WikiStructure, raw_path: Path) -> str:
    try:
        return raw_path.relative_to(structure.raw_dir).as_posix()
    except ValueError:
        return raw_path.name


def _merge_metadata_frontmatter(existing_content: str | None, new_content: str, metadata: dict[str, str]) -> str:
    """Merge caller-supplied metadata into the frontmatter of a raw write.

    ``existing_content`` (the current on-disk file, when present) provides the
    frontmatter base so unrelated fields such as ``source_url`` survive re-imports.
    ``new_content`` is the security-scanned replacement; its own frontmatter (if any)
    overrides the base, and caller metadata has the highest priority.
    """
    if not metadata:
        return new_content
    from myrm_agent_harness.toolkits.wiki.core.frontmatter_contract import (
        load_frontmatter_metadata,
        serialize_frontmatter_block,
    )

    base_meta: dict[str, object] = {}
    if existing_content:
        base_meta, _ = load_frontmatter_metadata(existing_content)
    new_meta, new_body = load_frontmatter_metadata(new_content)
    merged = {**base_meta, **new_meta, **metadata}
    return serialize_frontmatter_block(merged) + new_body.lstrip("\n")


def _read_raw_frontmatter_source_url(content: str) -> str | None:
    if not content.startswith("---"):
        return None
    end = content.find("\n---", 3)
    if end == -1:
        return None
    block = content[3:end]
    for line in block.splitlines():
        stripped = line.strip()
        if not stripped.startswith("source_url:"):
            continue
        value = stripped.split(":", 1)[1].strip().strip('"').strip("'")
        return value or None
    return None


def _extension_replace_allowed(
    *,
    caller: RawGateCaller,
    replace_source_url: str | None,
    existing_content: str,
) -> bool:
    if caller != "extension" or not replace_source_url:
        return False
    existing_url = _read_raw_frontmatter_source_url(existing_content)
    return existing_url == replace_source_url


def _publish_raw_impl(
    structure: WikiStructure,
    request: RawPublishRequest,
    *,
    caller: RawGateCaller,
) -> RawPublishResult:
    """Synchronous raw write logic (caller must hold vault lock)."""
    try:
        rel_path = _normalize_relative_path(request.relative_path)
        raw_path = structure.get_raw_file_path(rel_path)
    except RawGateError:
        raise
    except ValueError as exc:
        raise RawGateError("invalid_path", str(exc)) from exc

    try:
        write_content, security_redacted = _prepare_write_content(
            structure,
            relative_path=rel_path,
            content=request.content,
            caller=caller,
        )
    except RawGateError as exc:
        if exc.code == "raw_security_blocked":
            return RawPublishResult(
                relative_path=rel_path,
                absolute_path=raw_path,
                content_hash=compute_page_lease_hash(request.content),
                written=False,
                skipped=False,
                superseded=False,
                created=not raw_path.exists(),
                conflict_skipped=False,
                security_verdict="blocked",
                security_redacted=False,
                security_blocked=True,
            )
        raise

    created = not raw_path.exists()

    if request.metadata:
        # Caller metadata is structured provenance (e.g. source_chat), injected after the
        # content security scan — the scan targets free-text body content, not these keys.
        existing_content = raw_path.read_text(encoding="utf-8") if not created else None
        write_content = _merge_metadata_frontmatter(existing_content, write_content, request.metadata)

    new_hash = compute_page_lease_hash(write_content)
    previous_hash: str | None = None

    if not created:
        previous_hash = compute_page_lease_hash(raw_path.read_text(encoding="utf-8"))
        if previous_hash == new_hash:
            return RawPublishResult(
                relative_path=rel_path,
                absolute_path=raw_path,
                content_hash=new_hash,
                written=False,
                skipped=True,
                superseded=False,
                created=False,
                conflict_skipped=False,
                security_verdict="clean",
            )

        policy = request.conflict_policy
        if policy in {RawConflictPolicy.PUT_IF_ABSENT, RawConflictPolicy.SKIP}:
            return RawPublishResult(
                relative_path=rel_path,
                absolute_path=raw_path,
                content_hash=new_hash,
                written=False,
                skipped=True,
                superseded=False,
                created=False,
                conflict_skipped=True,
                security_verdict="clean",
            )

        if policy == RawConflictPolicy.FAIL:
            if _extension_replace_allowed(
                caller=caller,
                replace_source_url=request.replace_source_url,
                existing_content=raw_path.read_text(encoding="utf-8"),
            ):
                _write_raw_file(raw_path, write_content)
                append_log_entry(
                    structure,
                    WikiMapEvent(
                        event_type=WikiMapEventType.RAW_SUPERSEDE,
                        summary=(f"Extension re-clip replaced raw source {_relative_raw_display(structure, raw_path)}"),
                        details={
                            "caller": caller,
                            "reason": "extension_reclip_same_source_url",
                            "path": rel_path,
                            "previous_hash": previous_hash,
                            "content_hash": new_hash,
                            "source_url": request.replace_source_url,
                        },
                    ),
                )
                return _result_from_write(
                    rel_path=rel_path,
                    raw_path=raw_path,
                    content=write_content,
                    written=True,
                    skipped=False,
                    superseded=True,
                    created=False,
                    conflict_skipped=False,
                    security_redacted=security_redacted,
                )
            raise RawGateError(
                "raw_conflict",
                f"Raw source already exists with different content: {rel_path}",
            )

        if policy == RawConflictPolicy.SUPERSEDE:
            if caller != "settings":
                raise RawGateError(
                    "forbidden_for_caller",
                    "Raw supersede is settings-only.",
                )
            reason = request.supersede_reason.strip()
            if not reason:
                raise RawGateError(
                    "invalid_request",
                    "supersede_reason is required for raw supersede.",
                )
            _write_raw_file(raw_path, write_content)
            append_log_entry(
                structure,
                WikiMapEvent(
                    event_type=WikiMapEventType.RAW_SUPERSEDE,
                    summary=f"Superseded raw source {_relative_raw_display(structure, raw_path)}",
                    details={
                        "caller": caller,
                        "reason": reason,
                        "path": rel_path,
                        "previous_hash": previous_hash,
                        "content_hash": new_hash,
                    },
                ),
            )
            from myrm_agent_harness.toolkits.wiki.core.claims_contract import (
                record_raw_supersede_entry,
            )

            record_raw_supersede_entry(
                structure,
                rel_path=rel_path,
                previous_sha256=previous_hash or "",
                new_sha256=new_hash,
                reason=reason,
            )
            return _result_from_write(
                rel_path=rel_path,
                raw_path=raw_path,
                content=write_content,
                written=True,
                skipped=False,
                superseded=True,
                created=False,
                conflict_skipped=False,
                security_redacted=security_redacted,
            )

        raise RawGateError("invalid_request", f"Unsupported conflict policy: {policy}")

    _write_raw_file(raw_path, write_content)
    return _result_from_write(
        rel_path=rel_path,
        raw_path=raw_path,
        content=write_content,
        written=True,
        skipped=False,
        superseded=False,
        created=True,
        conflict_skipped=False,
        security_redacted=security_redacted,
    )


async def publish_raw(
    structure: WikiStructure,
    request: RawPublishRequest,
    *,
    caller: RawGateCaller,
) -> RawPublishResult:
    """Write content to raw/ with conflict policy enforcement."""
    async with _vault_lock(structure.base_dir):
        return _publish_raw_impl(structure, request, caller=caller)
