"""Memory write-path security scanner.

Scans memory content before persistence for prompt injection, credential
leaks, and invisible Unicode. Reuses existing security components from
``agent.security.detection`` — no new detection logic.

Processing tiers:
  - HIGH injection (score >= threshold): block write entirely
  - Credential leak detected: auto-redact, then store
  - Invisible Unicode found: auto-strip, then store
  - LOW injection (score < threshold): warn + store
  - Clean: store as-is

[INPUT]

[OUTPUT]
- scan_memory_content(): scan text, return ScanVerdict + cleaned text
- scan_and_clean_memory(): scan AnyMemory, mutate content fields in-place

[POS]
Memory write-path security scanner. Scans content, raw_exchange (ConversationMemory),
and trigger/action (ProceduralMemory) fields. Reuses prompt_guard (7+2 class injection detection),
leak_detector (25+ credential patterns + smart masking), content_boundary (zero-width
character stripping). Tiered processing: BLOCKED/REDACTED/WARN/CLEAN. Enforces worst-verdict
propagation across fields. Used in store/store_batch/update_memory/set_profile paths.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum

from myrm_agent_harness.core.security.detection.content_boundary import (
    has_invisible_unicode,
    strip_invisible_unicode,
)
from myrm_agent_harness.core.security.detection.harmful_state_detector import scan_for_harmful_states
from myrm_agent_harness.core.security.detection.leak_detector import redact_leaks, scan_for_leaks
from myrm_agent_harness.core.security.detection.prompt_guard import scan_input

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
    harmful_state_patterns: list[str] = field(default_factory=list)
    had_invisible_unicode: bool = False


class MemoryTaintedError(Exception):
    """Raised when memory content is blocked due to high-confidence injection."""

    def __init__(self, score: float, patterns: list[str]) -> None:
        self.score = score
        self.patterns = patterns
        super().__init__(f"Memory write blocked: injection score={score:.2f}, patterns={','.join(patterns)}")


def scan_memory_content(text: str, *, block_threshold: float = 0.8) -> ScanResult:
    """Scan a text field for security threats.

    Returns ScanResult with verdict and cleaned text. The caller decides
    how to handle each verdict (block, use cleaned text, or store as-is).
    """
    if not text:
        return ScanResult(verdict=ScanVerdict.CLEAN, cleaned_text=text)

    cleaned = text
    verdict = ScanVerdict.CLEAN
    injection_score = 0.0
    injection_patterns: list[str] = []
    credential_patterns: list[str] = []
    harmful_state_patterns: list[str] = []
    had_invisible = False

    harmful_matches = scan_for_harmful_states(text)
    if harmful_matches:
        harmful_state_patterns = harmful_matches
        return ScanResult(
            verdict=ScanVerdict.BLOCKED,
            cleaned_text=text,
            harmful_state_patterns=harmful_state_patterns,
        )

    guard_result = scan_input(text)
    if not guard_result.safe:
        injection_score = guard_result.max_score
        injection_patterns = guard_result.patterns
        if injection_score >= block_threshold:
            return ScanResult(
                verdict=ScanVerdict.BLOCKED,
                cleaned_text=text,
                injection_score=injection_score,
                injection_patterns=injection_patterns,
            )
        verdict = ScanVerdict.WARN

    cred_matches = scan_for_leaks(text)
    if cred_matches:
        credential_patterns = cred_matches
        cleaned = redact_leaks(cleaned)
        verdict = ScanVerdict.REDACTED

    if has_invisible_unicode(cleaned):
        had_invisible = True
        cleaned = strip_invisible_unicode(cleaned)
        if verdict == ScanVerdict.CLEAN:
            verdict = ScanVerdict.WARN

    cleaned = _apply_pii_pseudonymization(cleaned)

    return ScanResult(
        verdict=verdict,
        cleaned_text=cleaned,
        injection_score=injection_score,
        injection_patterns=injection_patterns,
        credential_patterns=credential_patterns,
        harmful_state_patterns=harmful_state_patterns,
        had_invisible_unicode=had_invisible,
    )


PseudonymizeFn = Callable[[str], str]

_pii_pseudonymizer: PseudonymizeFn | None = None


def set_pii_pseudonymizer(fn: PseudonymizeFn | None) -> None:
    """Register a PII pseudonymization function (called by agent layer at session start)."""
    global _pii_pseudonymizer
    _pii_pseudonymizer = fn


def _apply_pii_pseudonymization(text: str) -> str:
    """Apply PII pseudonymization via the registered function (if any)."""
    if _pii_pseudonymizer is None:
        return text
    return _pii_pseudonymizer(text)


def _handle_blocked_verdict(result: ScanResult, content: str) -> ScanResult:
    """Handle BLOCKED verdict by suspending execution for user approval."""
    from myrm_agent_harness.core.security.execution_policy import ApprovalContract, suspend_execution

    if result.harmful_state_patterns:
        reason = f"Harmful psychological state detected: {','.join(result.harmful_state_patterns)}"
        payload = {"harmful_state_patterns": result.harmful_state_patterns, "content": content}
    else:
        reason = f"High-confidence prompt injection detected (score={result.injection_score:.2f})"
        payload = {
            "injection_score": result.injection_score,
            "injection_patterns": result.injection_patterns,
            "content": content,
        }

    contract = ApprovalContract[dict[str, object]](
        action_type="memory_mutation",
        payload=payload,
        reason=reason,
        severity="critical",
    )
    decision = suspend_execution(contract)

    if isinstance(decision, dict) and decision.get("decision") == "approve":
        logger.warning("Memory mutation approved by user despite BLOCKED verdict")
        edited_content = content
        if (
            "edited_payload" in decision
            and isinstance(decision["edited_payload"], dict)
            and "content" in decision["edited_payload"]
        ):
            edited_content = str(decision["edited_payload"]["content"])

        return ScanResult(
            verdict=ScanVerdict.CLEAN,
            cleaned_text=edited_content,
            injection_score=result.injection_score,
            injection_patterns=result.injection_patterns,
            harmful_state_patterns=result.harmful_state_patterns,
        )
    if result.harmful_state_patterns:
        raise MemoryTaintedError(1.0, result.harmful_state_patterns)
    raise MemoryTaintedError(result.injection_score, result.injection_patterns)


def scan_and_clean_memory(memory: object, *, block_threshold: float = 0.8) -> ScanResult:
    """Scan all text fields of a memory object and clean in-place.

    Scans ``content`` (all memory types), ``raw_exchange`` (ConversationMemory),
    and ``trigger``/``action`` (ProceduralMemory). Returns the worst-case ScanResult
    across fields. Raises MemoryTaintedError if any field triggers BLOCKED verdict and is denied.
    """
    from myrm_agent_harness.toolkits.memory.types import ConversationMemory, ProceduralMemory

    content = getattr(memory, "content", "")
    result = scan_memory_content(content, block_threshold=block_threshold)

    if result.verdict == ScanVerdict.BLOCKED:
        result = _handle_blocked_verdict(result, content)

    if result.cleaned_text != content:
        memory.content = result.cleaned_text  # type: ignore[attr-defined]

    worst = result

    if isinstance(memory, ConversationMemory):
        raw_exchange = getattr(memory, "raw_exchange", "")
        if raw_exchange:
            raw_result = scan_memory_content(raw_exchange, block_threshold=block_threshold)
            if raw_result.verdict == ScanVerdict.BLOCKED:
                raw_result = _handle_blocked_verdict(raw_result, raw_exchange)
            if raw_result.cleaned_text != raw_exchange:
                memory.raw_exchange = raw_result.cleaned_text  # type: ignore[attr-defined]
            if _VERDICT_SEVERITY[raw_result.verdict] > _VERDICT_SEVERITY[worst.verdict]:
                worst = raw_result

    if isinstance(memory, ProceduralMemory):
        for field_name in ("trigger", "action"):
            field_val = getattr(memory, field_name, "")
            if not field_val:
                continue
            field_result = scan_memory_content(field_val, block_threshold=block_threshold)
            if field_result.verdict == ScanVerdict.BLOCKED:
                field_result = _handle_blocked_verdict(field_result, field_val)
            if field_result.cleaned_text != field_val:
                setattr(memory, field_name, field_result.cleaned_text)
            if _VERDICT_SEVERITY[field_result.verdict] > _VERDICT_SEVERITY[worst.verdict]:
                worst = field_result

    _log_scan_result(worst, content)
    return worst


def _log_scan_result(result: ScanResult, content: str) -> None:
    """Log, audit, and record metrics for scan results."""
    get_scan_metrics().record(result.verdict)

    if result.verdict == ScanVerdict.CLEAN:
        return

    snippet = content[:100].replace("\n", " ")
    reason_parts: list[str] = []

    if result.verdict == ScanVerdict.BLOCKED:
        if result.harmful_state_patterns:
            reason_parts.append(f"harmful_states={','.join(result.harmful_state_patterns)}")
        else:
            reason_parts.append(f"score={result.injection_score:.2f}")
            reason_parts.append(f"patterns={','.join(result.injection_patterns)}")
        logger.warning("[MEMORY_SCAN] BLOCKED %s snippet=%.100s", " ".join(reason_parts), snippet)
    elif result.verdict == ScanVerdict.REDACTED:
        reason_parts.append(f"credentials={','.join(result.credential_patterns)}")
        logger.warning("[MEMORY_SCAN] REDACTED %s snippet=%.100s", " ".join(reason_parts), snippet)
    elif result.verdict == ScanVerdict.WARN:
        if result.injection_patterns:
            reason_parts.append(f"injection={','.join(result.injection_patterns)}")
        if result.had_invisible_unicode:
            reason_parts.append("invisible_unicode=stripped")
        logger.warning("[MEMORY_SCAN] WARN %s snippet=%.100s", " ".join(reason_parts), snippet)

    _record_audit(result, reason_parts)


def _record_audit(result: ScanResult, reason_parts: list[str]) -> None:
    """Record scan result to security audit trail (best-effort)."""
    try:
        from myrm_agent_harness.core.security.audit import record_decision

        decision = "DENY" if result.verdict == ScanVerdict.BLOCKED else "SCAN_FINDING"
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
