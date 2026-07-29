"""Wiki raw write security pre-scan hook."""

from __future__ import annotations

from myrm_agent_harness.core.security.persistence.content_scan import (
    PersistScanProfile,
    PersistScanResult,
    PersistScanVerdict,
    scan_persistable_content,
)
from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure
from myrm_agent_harness.toolkits.wiki.pipeline.cognitive_map.events import WikiMapEvent, WikiMapEventType
from myrm_agent_harness.toolkits.wiki.pipeline.cognitive_map.writer import append_log_entry
from myrm_agent_harness.toolkits.wiki.pipeline.raw_gate.errors import RawGateError


def scan_raw_publish_content(content: str, *, caller: str = "settings") -> PersistScanResult:
    """Scan raw vault content before write."""
    return scan_persistable_content(
        content,
        profile=PersistScanProfile.WIKI_RAW,
        wiki_raw_caller=caller,
    )


def scan_publish_article_content(content: str) -> PersistScanResult:
    """Scan compiled wiki article before publish."""
    return scan_persistable_content(content, profile=PersistScanProfile.WIKI_PUBLISH)


def apply_raw_security_scan(
    structure: WikiStructure,
    *,
    relative_path: str,
    content: str,
    caller: str,
) -> str:
    """Return write-safe content; raise RawGateError on block; append audit on redact/warn."""
    scan = scan_raw_publish_content(content, caller=caller)
    if scan.verdict == PersistScanVerdict.BLOCKED:
        raise RawGateError(
            "raw_security_blocked",
            f"Raw source rejected due to sensitive content: {relative_path}",
        )

    if scan.verdict != PersistScanVerdict.CLEAN:
        append_log_entry(
            structure,
            WikiMapEvent(
                event_type=WikiMapEventType.RAW_SECURITY,
                summary=f"Raw security {scan.verdict.value}: {relative_path}",
                details={
                    "caller": caller,
                    "path": relative_path,
                    "verdict": scan.verdict.value,
                    "finding_codes": scan.finding_codes,
                    "credential_patterns": scan.credential_patterns,
                },
            ),
        )
    return scan.cleaned_text
