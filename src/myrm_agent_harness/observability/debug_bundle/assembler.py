"""Session debug bundle assembler.

[INPUT]
- observability.audit_trail.collector::DualTrackAuditCollector (POS: intent/act entries)
- observability.audit_trail.redactor::sanitize_sensitive_data, compute_redaction_fingerprint (POS: scrub + seal)
- Plain mappings for memory trace, failure summary, config snapshot (POS: caller-supplied evidence)

[OUTPUT]
- assemble_debug_bundle: one redacted dossier with required-sections gate

[POS]
Framework-level assembler: callers pass already-collected evidence, the
assembler redacts, caps size, and seals. No agent/eval imports.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from myrm_agent_harness.observability.audit_trail.collector import DualTrackAuditCollector
from myrm_agent_harness.observability.audit_trail.redactor import (
    compute_redaction_fingerprint,
    sanitize_sensitive_data,
)
from myrm_agent_harness.observability.debug_bundle.types import (
    BundleCompleteness,
    BundleSection,
    DebugBundle,
    utc_now_iso,
)

REQUIRED_SECTIONS: tuple[str, ...] = ("audit", "memory_trace", "failure", "config")

_MAX_ITEMS_PER_SECTION = 200
_MAX_STRING_CHARS = 8000


def _cap_value(value: Any) -> tuple[Any, bool]:
    """Truncate oversized strings/lists, reporting whether truncation happened."""
    if isinstance(value, str) and len(value) > _MAX_STRING_CHARS:
        return value[:_MAX_STRING_CHARS] + "…[truncated]", True
    if isinstance(value, list) and len(value) > _MAX_ITEMS_PER_SECTION:
        return [*value[:_MAX_ITEMS_PER_SECTION], "…[truncated]"], True
    if isinstance(value, dict):
        truncated = False
        capped: dict[str, Any] = {}
        for key, item in value.items():
            capped_item, was_cut = _cap_value(item)
            truncated = truncated or was_cut
            capped[str(key)] = capped_item
        return capped, truncated
    return value, False


def _entries_to_payload(collector: DualTrackAuditCollector, session_id: str, agent_id: str) -> dict[str, Any]:
    entries = collector.list_entries(session_id=session_id, agent_id=agent_id, limit=_MAX_ITEMS_PER_SECTION)
    summary = collector.get_summary_stats(session_id=session_id, agent_id=agent_id)
    return {
        "entry_count": len(entries),
        "summary": {
            "total_entries": summary.total_entries,
            "permitted_count": summary.permitted_count,
            "refused_count": summary.refused_count,
            "failed_count": summary.failed_count,
            "compliance_rate": summary.compliance_rate,
        },
    }


def assemble_debug_bundle(
    *,
    collector: DualTrackAuditCollector,
    session_id: str,
    agent_id: str,
    memory_trace: Mapping[str, Any] | None = None,
    failure_summary: Mapping[str, Any] | None = None,
    config_snapshot: Mapping[str, Any] | None = None,
) -> DebugBundle:
    """Assemble one redacted session dossier.

    Missing optional sections mark the bundle PARTIAL instead of failing,
    so a bundle is always available for debugging.
    """
    provided: dict[str, Mapping[str, Any] | None] = {
        "memory_trace": memory_trace,
        "failure": failure_summary,
        "config": config_snapshot,
    }
    sections = [
        BundleSection(
            name="audit",
            payload=dict(_entries_to_payload(collector, session_id, agent_id)),
        )
    ]
    missing: list[str] = []
    for name in ("memory_trace", "failure", "config"):
        evidence = provided[name]
        if evidence is None:
            missing.append(name)
            continue
        capped, was_cut = _cap_value(dict(evidence))
        sections.append(BundleSection(name=name, payload=capped, truncated=was_cut))
    redacted_sections = [
        BundleSection(name=section.name, payload=sanitize_sensitive_data(section.payload), truncated=section.truncated)
        for section in sections
    ]
    fingerprint = compute_redaction_fingerprint(
        "|".join(f"{section.name}:{len(str(section.payload))}" for section in redacted_sections)
    )
    return DebugBundle(
        session_id=session_id,
        agent_id=agent_id,
        created_at=utc_now_iso(),
        completeness=BundleCompleteness.PARTIAL if missing else BundleCompleteness.COMPLETE,
        missing_sections=missing,
        sections=redacted_sections,
        fingerprint=fingerprint,
    )
