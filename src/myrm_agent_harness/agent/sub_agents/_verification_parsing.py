"""Structured verdict parsing and SSE emission for adversarial verification.

[INPUT]
- core.events.types::AgentEventType (POS: VERIFICATION_VERDICT event type)
- utils.runtime.progress_sink::get_tool_progress_sink (POS: SSE emission sink)
- utils.json_parsing::parse_llm_json_object (POS: robust JSON object extraction from LLM output — fences, prose, bare control chars, trailing commas; requires the ``verdict`` key)

[OUTPUT]
- VerificationVerdict: Parsed verdict from verifier output
- _parse_verdict, _emit_verification_verdict: Parsing and event helpers

[POS]
Shared verification parsing for sub_agents verifier rounds and delegate verification.
"""

from __future__ import annotations

from dataclasses import dataclass

from myrm_agent_harness.utils.json_parsing import parse_llm_json_object
from myrm_agent_harness.utils.logger_utils import get_agent_logger

logger = get_agent_logger(__name__)

__all__ = ["VerificationVerdict", "_emit_verification_verdict", "_parse_verdict"]


@dataclass(frozen=True, slots=True)
class VerificationVerdict:
    """Parsed verdict from a Verifier agent's structured JSON output."""

    passed: bool
    summary: str
    confidence: str
    findings: list[dict[str, str]]
    raw: str


def _parse_verdict(raw_result: str) -> VerificationVerdict:
    """Extract the verification verdict from a Verifier agent's output.

    Pure parsing: whether a PASS is backed by real execution is decided from the executor's
    execution evidence in the verifier round, never from words in the verifier's text.
    """
    data = parse_llm_json_object(raw_result, require_key="verdict")

    if data is not None:
        try:
            verdict_str = str(data.get("verdict", "")).strip().upper()
            findings_raw = data.get("findings", [])
            findings: list[dict[str, str]] = []
            if isinstance(findings_raw, list):
                findings = [{k: str(v) for k, v in item.items()} for item in findings_raw if isinstance(item, dict)]
            return VerificationVerdict(
                passed=verdict_str == "PASS",
                summary=str(data.get("summary", "")),
                confidence=str(data.get("confidence", "UNKNOWN")),
                findings=findings,
                raw=raw_result,
            )
        except (ValueError, TypeError):
            pass

    upper = raw_result.upper()
    if '"VERDICT": "PASS"' in upper or '"VERDICT":"PASS"' in upper:
        return VerificationVerdict(
            passed=True,
            summary="JSON parse failed; keyword PASS detected",
            confidence="LOW",
            findings=[],
            raw=raw_result,
        )

    return VerificationVerdict(
        passed=False,
        summary="Unable to parse verdict; defaulting to FAIL",
        confidence="LOW",
        findings=[],
        raw=raw_result,
    )


async def _emit_verification_verdict(
    *,
    verdict: VerificationVerdict,
    round_num: int,
    max_rounds: int,
    worker_type: str,
    verifier_type: str,
    has_diff: bool,
) -> None:
    """Emit a VERIFICATION_VERDICT event via the active ToolProgressSink."""
    from myrm_agent_harness.core.events.types import AgentEventType
    from myrm_agent_harness.utils.runtime.progress_sink import get_tool_progress_sink

    sink = get_tool_progress_sink()
    if not sink:
        return

    findings_brief = [
        {"severity": f.get("severity", "UNKNOWN"), "description": f.get("description", "")[:200]}
        for f in verdict.findings[:5]
    ]

    try:
        await sink.emit(
            {
                "type": AgentEventType.VERIFICATION_VERDICT.value,
                "data": {
                    "passed": verdict.passed,
                    "summary": verdict.summary[:500],
                    "confidence": verdict.confidence,
                    "round": round_num,
                    "max_rounds": max_rounds,
                    "worker_type": worker_type,
                    "verifier_type": verifier_type,
                    "has_workspace_diff": has_diff,
                    "findings": findings_brief,
                },
            }
        )
    except Exception as exc:
        logger.debug("[verification] Failed to emit VERIFICATION_VERDICT event: %s", exc)
