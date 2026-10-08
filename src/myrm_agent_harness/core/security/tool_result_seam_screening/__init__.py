"""Tool result seam screening and in-place malicious instruction redactor suite.

Exports high-level screening suite and core component interfaces.
Strict typing: No `Any` types allowed.
"""

from __future__ import annotations

import time
from collections.abc import Callable

from .chunk_packer import extract_units, split_paragraphs
from .injection_detector import InjectionDetector, match_local_rules
from .inplace_redactor import redact_in_place
from .types import (
    ParagraphChunk,
    ScreeningEngineMode,
    ScreeningPolicy,
    ScreeningVerdictStatus,
    ScreeningVerdictUnit,
    SeamScreenResult,
)


class ToolResultSeamScreeningSuite:
    """Industrial-grade gateway for screening tool results at the physical seam before LLM injection."""

    def __init__(
        self,
        policy: ScreeningPolicy | None = None,
        fast_classifier: Callable[[str], float] | None = None,
    ) -> None:
        self.policy = policy or ScreeningPolicy()
        self.detector = InjectionDetector(policy=self.policy, fast_classifier=fast_classifier)

    def screen(self, tool_name: str, tool_result: str) -> SeamScreenResult:
        """Screen and in-place redact tool output at the seam.

        Guaranteed 'Never Raise' contract: any unexpected parsing failure degrades
        to fail-open untouched output.
        """
        start_time = time.perf_counter()

        if not tool_result or not tool_result.strip():
            latency = (time.perf_counter() - start_time) * 1000.0
            return SeamScreenResult(
                verdict_status=ScreeningVerdictStatus.CLEAN,
                screening_mode=ScreeningEngineMode.LOCAL_ONLY,
                total_units=0,
                flagged_units=0,
                flagged_chunk_ids=[],
                redacted_content=tool_result,
                latency_ms=latency,
                reason="empty_result",
                scores={},
            )

        try:
            parsed, chunks = extract_units(
                tool_name=tool_name,
                tool_result=tool_result,
                max_chars=self.policy.max_chunk_chars,
            )

            if not chunks:
                latency = (time.perf_counter() - start_time) * 1000.0
                return SeamScreenResult(
                    verdict_status=ScreeningVerdictStatus.CLEAN,
                    screening_mode=ScreeningEngineMode.LOCAL_ONLY,
                    total_units=0,
                    flagged_units=0,
                    flagged_chunk_ids=[],
                    redacted_content=tool_result,
                    latency_ms=latency,
                    reason="no_extractable_units",
                    scores={},
                )

            verdict_units, engine_mode, degradation_note = self.detector.detect_all(chunks)
            flagged_ids = {unit.chunk_id for unit in verdict_units if unit.flagged}
            scores_map = {unit.chunk_id: round(unit.score, 3) for unit in verdict_units}

            if not flagged_ids:
                latency = (time.perf_counter() - start_time) * 1000.0
                return SeamScreenResult(
                    verdict_status=ScreeningVerdictStatus.CLEAN,
                    screening_mode=engine_mode,
                    total_units=len(chunks),
                    flagged_units=0,
                    flagged_chunk_ids=[],
                    redacted_content=tool_result,
                    latency_ms=latency,
                    reason=degradation_note or "clean_content",
                    scores=scores_map,
                )

            redacted_text = redact_in_place(
                tool_name=tool_name,
                raw_result=tool_result,
                parsed=parsed,
                chunks=chunks,
                flagged_ids=flagged_ids,
                policy=self.policy,
            )

            latency = (time.perf_counter() - start_time) * 1000.0
            return SeamScreenResult(
                verdict_status=ScreeningVerdictStatus.REDACTED,
                screening_mode=engine_mode,
                total_units=len(chunks),
                flagged_units=len(flagged_ids),
                flagged_chunk_ids=sorted(flagged_ids),
                redacted_content=redacted_text,
                latency_ms=latency,
                reason=degradation_note or f"redacted_{len(flagged_ids)}_malicious_units",
                scores=scores_map,
            )

        except Exception as exc:
            latency = (time.perf_counter() - start_time) * 1000.0
            return SeamScreenResult(
                verdict_status=ScreeningVerdictStatus.FAIL_OPEN,
                screening_mode=ScreeningEngineMode.LOCAL_ONLY,
                total_units=0,
                flagged_units=0,
                flagged_chunk_ids=[],
                redacted_content=tool_result,
                latency_ms=latency,
                reason=f"fail_open_exception:{type(exc).__name__}",
                scores={},
            )


__all__ = [
    "extract_units",
    "split_paragraphs",
    "match_local_rules",
    "redact_in_place",
    "ParagraphChunk",
    "ScreeningEngineMode",
    "ScreeningPolicy",
    "ScreeningVerdictStatus",
    "ScreeningVerdictUnit",
    "SeamScreenResult",
    "ToolResultSeamScreeningSuite",
]
