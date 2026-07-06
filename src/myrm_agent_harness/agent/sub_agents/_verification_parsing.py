"""Structured verdict parsing and SSE emission for adversarial verification."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

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


_VERDICT_JSON_RE = re.compile(r"\{[\s\S]*\"verdict\"\s*:", re.IGNORECASE)


def _parse_verdict(raw_result: str) -> VerificationVerdict:
    """Extract the verification verdict from a Verifier agent's output."""
    text = raw_result.strip()

    fenced = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", text, re.IGNORECASE)
    if fenced:
        text = fenced.group(1)
    else:
        match = _VERDICT_JSON_RE.search(text)
        if match:
            start = match.start()
            depth, end = 0, start
            for i in range(start, len(text)):
                if text[i] == "{":
                    depth += 1
                elif text[i] == "}":
                    depth -= 1
                    if depth == 0:
                        end = i + 1
                        break
            text = text[start:end]

    def _enforce_evidence(passed: bool, summary: str, raw: str) -> tuple[bool, str]:
        if not passed:
            return passed, summary
        upper = raw.upper()
        if "STDOUT" not in upper and "STDERR" not in upper and "EXECUTION" not in upper and "TRACEBACK" not in upper:
            return False, (
                "FAIL: Validation rejected. You must provide actual execution log "
                "evidence (STDOUT/STDERR/EXECUTION) to grant a PASS."
            )
        return passed, summary

    try:
        data = json.loads(text)
        verdict_str = str(data.get("verdict", "")).strip().upper()
        passed = verdict_str == "PASS"
        summary = str(data.get("summary", ""))

        passed, summary = _enforce_evidence(passed, summary, raw_result)

        findings_raw = data.get("findings", [])
        findings = [{k: str(v) for k, v in item.items()} for item in findings_raw if isinstance(item, dict)]
        return VerificationVerdict(
            passed=passed,
            summary=summary,
            confidence=str(data.get("confidence", "UNKNOWN")),
            findings=findings,
            raw=raw_result,
        )
    except (json.JSONDecodeError, ValueError):
        pass

    upper = raw_result.upper()
    if '"VERDICT": "PASS"' in upper or '"VERDICT":"PASS"' in upper:
        passed, summary = _enforce_evidence(True, "JSON parse failed; keyword PASS detected", raw_result)
        return VerificationVerdict(
            passed=passed,
            summary=summary,
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
        await sink.emit({
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
        })
    except Exception as exc:
        logger.debug("[verification] Failed to emit VERIFICATION_VERDICT event: %s", exc)
