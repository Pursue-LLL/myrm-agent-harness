"""Memory write-path security scanner.

Scans memory content before persistence for prompt injection, credential
leaks, instruction-shape poisoning, password-like secrets, and invisible
Unicode. Reuses existing security components from
``core.security.detection``.

Processing tiers:
  - HIGH injection (score >= threshold): block write entirely
  - Credential leak / password-like detected: auto-redact, then store
  - Instruction-shape found: warn + store
  - Invisible Unicode found: auto-strip, then store
  - LOW injection (score < threshold): warn + store
  - Clean: store as-is

[INPUT]
- core.security.persistence.content_scan::scan_persistable_content (POS: Persistence-scan SSOT — injection / harmful-state / PII-pseudonymize / leak / boundary verdicts.)
- core.security.persistence.content_scan::set_pii_pseudonymizer (POS: Context-local regex PII pseudonymization closure, inherited by fire-and-forget tasks.)
- memory._internal.storage::MemoryError (POS: Base class of memory operation errors, so MemoryTaintedError is handled like every other rejected write.)

[OUTPUT]
- scan_memory_content(): scan text, return ScanVerdict + cleaned text
- scan_and_clean_memory(): scan AnyMemory, mutate content fields in-place
- reject_blocked(): count, audit and log a BLOCKED verdict, then reject the write
- reject_if_blocked(): read-only up-front BLOCKED probe for write buffers
- MemoryTaintedError: rejected write; ``str()`` is safe to show to end users
- set_pii_pseudonymizer(): register the context-local regex PII closure applied before persistence

[POS]
Memory write-path security scanner. Scans content, raw_exchange (ConversationMemory,
scanned without its own role labels), trigger/action (ProceduralMemory) and the
summary_l0/overview_l1 gists (re-derived from the cleaned content when they are its prefixes).
A BLOCKED verdict is a plain rejection (counted, audited, logged without the text, then
MemoryTaintedError) — there is no approval path, so every caller, in or out of an agent run, behaves alike.
Reuses prompt_guard (9-class injection detection),
leak_detector (25+ credential patterns + smart masking + password-like heuristic),
instruction_shape (6-class bilingual instruction-shape detection),
content_boundary (zero-width character stripping), and the context-local PII
pseudonymization closure. Tiered processing:
BLOCKED/REDACTED/WARN/CLEAN. Enforces worst-verdict propagation across fields.
Used in store/store_batch/update_memory/set_profile paths.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import Literal, NoReturn

from myrm_agent_harness.core.security.persistence.content_scan import (
    PersistScanProfile,
    PersistScanVerdict,
    scan_persistable_content,
)
from myrm_agent_harness.core.security.persistence.content_scan import (
    set_pii_pseudonymizer as _set_core_pii_pseudonymizer,
)
from myrm_agent_harness.toolkits.memory._internal.storage import MemoryError

logger = logging.getLogger(__name__)


class ScanVerdict(StrEnum):
    CLEAN = "clean"
    WARN = "warn"
    REDACTED = "redacted"
    BLOCKED = "blocked"


_VERDICT_SEVERITY: dict[ScanVerdict, int] = {
    ScanVerdict.CLEAN: 0,
    ScanVerdict.WARN: 1,
    ScanVerdict.REDACTED: 2,
    ScanVerdict.BLOCKED: 3,
}


@dataclass(frozen=True, slots=True)
class ScanResult:
    """Result of scanning a single text field."""

    verdict: ScanVerdict
    cleaned_text: str
    injection_score: float = 0.0
    injection_patterns: list[str] = field(default_factory=list)
    credential_patterns: list[str] = field(default_factory=list)
    instruction_shape_patterns: list[str] = field(default_factory=list)
    harmful_state_patterns: list[str] = field(default_factory=list)
    had_invisible_unicode: bool = False


class MemoryTaintedError(MemoryError):
    """Raised when the write scan rejects a memory (BLOCKED verdict).

    ``str()`` is phrased for end users (REST ``detail``, UI toast): it names no detector,
    score or pattern. ``score`` / ``patterns`` carry the detector detail for logs and tests.
    """

    def __init__(self, score: float, patterns: list[str], *, harmful_state: bool = False) -> None:
        self.score = score
        self.patterns = patterns
        self.harmful_state = harmful_state
        super().__init__(
            "Memory not saved: sensitive personal-state content is not stored."
            if harmful_state
            else "Memory not saved: the text reads like an instruction to the assistant, not a fact or preference."
        )


def _map_persist_verdict(verdict: PersistScanVerdict) -> ScanVerdict:
    return ScanVerdict(verdict.value)


def scan_memory_content(text: str, *, block_threshold: float = 0.8, pseudonymize: bool = True) -> ScanResult:
    """Scan a text field for security threats.

    ``pseudonymize=False`` skips the (stateful) PII closure for callers that only need the verdict.
    """
    persist = scan_persistable_content(
        text,
        profile=PersistScanProfile.MEMORY_WRITE,
        block_threshold=block_threshold,
        pseudonymize=pseudonymize,
    )
    return ScanResult(
        verdict=_map_persist_verdict(persist.verdict),
        cleaned_text=persist.cleaned_text,
        injection_score=persist.injection_score,
        injection_patterns=persist.injection_patterns,
        credential_patterns=persist.credential_patterns,
        instruction_shape_patterns=persist.instruction_shape_patterns,
        harmful_state_patterns=persist.harmful_state_patterns,
        had_invisible_unicode=persist.had_invisible_unicode,
    )


PseudonymizeFn = Callable[[str], str]


def set_pii_pseudonymizer(fn: PseudonymizeFn | None) -> None:
    """Register a PII pseudonymization function for the current context.

    Called by the agent layer at session start; stored in a ContextVar so
    fire-and-forget memory writes inherit it via task context snapshot.
    """
    _set_core_pii_pseudonymizer(fn)


def _apply_pii_pseudonymization(text: str) -> str:
    """Apply PII pseudonymization via the registered function (if any)."""
    from myrm_agent_harness.core.security.persistence.content_scan import get_pii_pseudonymizer

    fn = get_pii_pseudonymizer()
    if fn is None:
        return text
    return fn(text)


def reject_blocked(result: ScanResult) -> NoReturn:
    """Count, audit and log a BLOCKED verdict, then reject the write.

    The log line names the detector findings only: a BLOCKED text is returned by the scan
    before credential redaction, so it must never be echoed.
    """
    get_scan_metrics().record(ScanVerdict.BLOCKED)
    if result.harmful_state_patterns:
        detail = f"harmful_states={','.join(result.harmful_state_patterns)}"
    else:
        detail = f"score={result.injection_score:.2f} patterns={','.join(result.injection_patterns)}"
    logger.warning("[MEMORY_SCAN] BLOCKED %s", detail)
    _record_audit(result, [detail])
    if result.harmful_state_patterns:
        raise MemoryTaintedError(1.0, result.harmful_state_patterns, harmful_state=True)
    raise MemoryTaintedError(result.injection_score, result.injection_patterns)


def reject_if_blocked(text: str, *, block_threshold: float) -> None:
    """Reject ``text`` up front when the write scan would block it.

    Read-only probe for write buffers: nothing is cleaned or pseudonymized and only a
    rejection is counted, so the scan that later persists an accepted memory still
    records it exactly once.
    """
    result = scan_memory_content(text, block_threshold=block_threshold, pseudonymize=False)
    if result.verdict == ScanVerdict.BLOCKED:
        reject_blocked(result)


def _scan_field(text: str, block_threshold: float) -> ScanResult:
    """Scan one text field; a BLOCKED verdict rejects the whole write."""
    result = scan_memory_content(text, block_threshold=block_threshold)
    if result.verdict == ScanVerdict.BLOCKED:
        reject_blocked(result)
    return result


_USER_LABEL = "User: "  # role labels the chunker writes into ConversationMemory.raw_exchange
_ASSISTANT_LABEL = "\nAssistant: "


def _scan_exchange(raw_exchange: str, user_turn: str, user_result: ScanResult, block_threshold: float) -> ScanResult:
    """Scan a verbatim ``raw_exchange`` without tripping on its own role labels.

    Scanned whole, the chunker's structural ``Assistant:`` line matches the fake-role-line
    injection heuristic on every exchange. For the exact ``User: <turn>\\nAssistant: <reply>``
    layout only the reply is scanned (the turn reuses ``user_result``) and both cleaned bodies
    are re-attached to the original labels; any other layout is scanned whole.
    """
    head = f"{_USER_LABEL}{user_turn}{_ASSISTANT_LABEL}"
    if not raw_exchange.startswith(head):
        return _scan_field(raw_exchange, block_threshold)

    reply_result = _scan_field(raw_exchange[len(head) :], block_threshold)
    worst = max(user_result, reply_result, key=lambda r: _VERDICT_SEVERITY[r.verdict])
    cleaned = f"{_USER_LABEL}{user_result.cleaned_text}{_ASSISTANT_LABEL}{reply_result.cleaned_text}"
    return replace(worst, cleaned_text=cleaned)


# Content-gist fields of every memory with their length contracts (types.py summary_l0 / overview_l1).
_GIST_LIMITS = (("summary_l0", 120), ("overview_l1", 400))


def _sync_gists(memory: object, raw: str, cleaned: str) -> list[str]:
    """Re-derive the gists that are plain prefixes of ``raw`` from the scanned ``cleaned`` text.

    A prefix cut from the raw text can keep a fragment of a token that the cut split in two,
    which no credential pattern matches, so it follows the cleaned content instead of being
    scanned. Returns the names of gists the writer authored independently, which need a scan.
    """
    authored: list[str] = []
    for name, limit in _GIST_LIMITS:
        gist = getattr(memory, name, "")
        if gist == raw.strip()[:limit].strip():
            setattr(memory, name, cleaned.strip()[:limit].strip())
        elif gist:
            authored.append(name)
    return authored


def scan_and_clean_memory(memory: object, *, block_threshold: float = 0.8) -> ScanResult:
    """Scan all text fields of a memory object and clean in-place.

    Scans ``content`` (all memory types), ``raw_exchange`` (ConversationMemory),
    ``trigger``/``action`` (ProceduralMemory) and the ``summary_l0``/``overview_l1`` gists
    (re-derived from the cleaned content, or scanned when authored independently). Returns the
    worst-case ScanResult across fields. Raises MemoryTaintedError if any field is BLOCKED.
    """
    from myrm_agent_harness.toolkits.memory.types import ConversationMemory, ProceduralMemory

    content = getattr(memory, "content", "")
    result = _scan_field(content, block_threshold)

    if result.cleaned_text != content:
        memory.content = result.cleaned_text  # type: ignore[attr-defined]

    worst = result
    authored_gists = _sync_gists(memory, content, result.cleaned_text)

    if isinstance(memory, ConversationMemory):
        raw_exchange = getattr(memory, "raw_exchange", "")
        if raw_exchange:
            raw_result = _scan_exchange(raw_exchange, content, result, block_threshold)
            if raw_result.cleaned_text != raw_exchange:
                memory.raw_exchange = raw_result.cleaned_text
            if _VERDICT_SEVERITY[raw_result.verdict] > _VERDICT_SEVERITY[worst.verdict]:
                worst = raw_result

    rule_fields = ("trigger", "action") if isinstance(memory, ProceduralMemory) else ()
    for field_name in (*rule_fields, *authored_gists):
        field_val = getattr(memory, field_name, "")
        if not field_val:
            continue
        field_result = _scan_field(field_val, block_threshold)
        if field_result.cleaned_text != field_val:
            setattr(memory, field_name, field_result.cleaned_text)
        if _VERDICT_SEVERITY[field_result.verdict] > _VERDICT_SEVERITY[worst.verdict]:
            worst = field_result

    # Log the cleaned text: a raw snippet would copy the very secret the scan just redacted.
    _log_scan_result(worst, getattr(memory, "content", ""))
    return worst


def _log_scan_result(result: ScanResult, content: str) -> None:
    """Log, audit, and record metrics for an accepted write's scan result (BLOCKED never reaches here)."""
    get_scan_metrics().record(result.verdict)

    if result.verdict == ScanVerdict.CLEAN:
        return

    snippet = content[:100].replace("\n", " ")
    reason_parts: list[str] = []

    if result.verdict == ScanVerdict.REDACTED:
        reason_parts.append(f"credentials={','.join(result.credential_patterns)}")
        if result.instruction_shape_patterns:
            reason_parts.append(f"instruction_shape={','.join(result.instruction_shape_patterns)}")
        logger.warning("[MEMORY_SCAN] REDACTED %s snippet=%.100s", " ".join(reason_parts), snippet)
    elif result.verdict == ScanVerdict.WARN:
        if result.injection_patterns:
            reason_parts.append(f"injection={','.join(result.injection_patterns)}")
        if result.instruction_shape_patterns:
            reason_parts.append(f"instruction_shape={','.join(result.instruction_shape_patterns)}")
        if result.had_invisible_unicode:
            reason_parts.append("invisible_unicode=stripped")
        logger.warning("[MEMORY_SCAN] WARN %s snippet=%.100s", " ".join(reason_parts), snippet)

    _record_audit(result, reason_parts)


def _record_audit(result: ScanResult, reason_parts: list[str]) -> None:
    """Record scan result to security audit trail (best-effort)."""
    try:
        from myrm_agent_harness.core.security.audit import record_decision

        decision: Literal["DENY", "SCAN_FINDING"] = "DENY" if result.verdict == ScanVerdict.BLOCKED else "SCAN_FINDING"
        record_decision("memory_write", decision, f"verdict={result.verdict.value} {' '.join(reason_parts)}")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Scan metrics — lightweight counters for monitoring
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ScanMetricsSnapshot:
    """Immutable snapshot of scan counters."""

    total_scans: int
    blocked: int
    redacted: int
    warned: int
    clean: int
    blocked_rate: float


class _ScanMetrics:
    """Thread-safe scan counters. Singleton via get_scan_metrics()."""

    __slots__ = ("_by_verdict", "_lock", "_total")

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._total = 0
        self._by_verdict: dict[ScanVerdict, int] = {v: 0 for v in ScanVerdict}

    def record(self, verdict: ScanVerdict) -> None:
        with self._lock:
            self._total += 1
            self._by_verdict[verdict] += 1

    def snapshot(self) -> ScanMetricsSnapshot:
        with self._lock:
            total = self._total
            blocked = self._by_verdict[ScanVerdict.BLOCKED]
            return ScanMetricsSnapshot(
                total_scans=total,
                blocked=blocked,
                redacted=self._by_verdict[ScanVerdict.REDACTED],
                warned=self._by_verdict[ScanVerdict.WARN],
                clean=self._by_verdict[ScanVerdict.CLEAN],
                blocked_rate=blocked / total if total > 0 else 0.0,
            )

    def reset(self) -> None:
        with self._lock:
            self._total = 0
            for v in ScanVerdict:
                self._by_verdict[v] = 0


_scan_metrics: _ScanMetrics | None = None
_scan_metrics_lock = threading.Lock()


def get_scan_metrics() -> _ScanMetrics:
    """Get or create the global scan metrics singleton."""
    global _scan_metrics
    if _scan_metrics is None:
        with _scan_metrics_lock:
            if _scan_metrics is None:
                _scan_metrics = _ScanMetrics()
    return _scan_metrics
