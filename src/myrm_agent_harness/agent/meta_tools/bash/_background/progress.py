"""Progress-marker parser for background bash tasks.

Background tasks rarely call ``tools.notify()`` directly — that would require
the LLM to invoke PTC from inside its shell snippet, which is expensive in
tokens and intrusive in scripts. Instead, the script can simply ``print`` a
canonical marker line and this parser converts it into the same structured
``ptc_notify`` payload the rest of the system already understands.

Two surfaces are supported (in priority order):

1. **Explicit JSON markers** (zero ambiguity, recommended for new scripts):

   ``MYRM_PROGRESS {"percent": 42, "message": "Compiling..."}``
   ``MYRM_CHECKPOINT {"message": "Unit tests passed"}``

   Supported fields: ``percent`` (0-100, clamped), ``current`` + ``total``
   (auto-converted to percent + ``step_index`` / ``total_steps``),
   ``message``. Unknown fields are silently ignored — keep the surface tiny
   so new keys can be added without breaking older parsers.

2. **Heuristic plain output** (free for unannotated stdout from third-party
   tools): ``42%``, ``3/10 tests``, ``1.5/3.0 GiB``,
   ``Compiling ...``, ``Building ...``, ``Running ...``, ``Downloading ...``.

   Lines that look like error/fatal reports
   (``ERROR``/``ERR!``/``FATAL``/``EXCEPTION``/``TRACEBACK``/``PANIC``/
   ``CRITICAL``/``SEGFAULT``/``ABORT``) are intentionally ignored so a
   failure trace cannot be mistaken for build progress.

[INPUT]
- str: a single output line, already stripped of trailing newline.

[OUTPUT]
- ``dict[str, object] | None``: notify payload (``message``, optional
  ``progress`` / ``step_index`` / ``total_steps``) or ``None`` when the line
  has no recognisable progress signal.

[POS]
PTC-adjacent runtime helper. Pure stateless parsing — no I/O, no logging.
"""

from __future__ import annotations

import json
import re
from typing import Final

_MARKER_PROGRESS: Final[str] = "MYRM_PROGRESS"
_MARKER_CHECKPOINT: Final[str] = "MYRM_CHECKPOINT"

# Heuristic patterns are checked in order; first match wins. ``re.IGNORECASE``
# is intentional because LLM-emitted scripts vary in casing.
_PERCENT_RE: Final[re.Pattern[str]] = re.compile(r"\b(\d{1,3})\s*%")
_FRACTION_RE: Final[re.Pattern[str]] = re.compile(
    r"\b(\d+(?:\.\d+)?)\s*(?:/|of)\s*(\d+(?:\.\d+)?)\s*"
    r"(tests|steps|files|pages|tasks|items|GiB|MiB|MB|GB|KB)?\b",
    re.IGNORECASE,
)
_PHASE_RE: Final[re.Pattern[str]] = re.compile(
    r"^\s*(Compiling|Building|Running|Downloading|Installing|Linting|Testing|"
    r"Deploying|Packaging|Bundling)\b",
    re.IGNORECASE,
)
# Lines that obviously belong to an error report must not feed the progress
# bar — ``npm ERR! Disk 99% full`` was being shown as 99% progress, which is
# the exact opposite of the user's mental model. We err on the side of
# silence: anything that looks like an error trail just stays in stdout/stderr
# and is rendered as plain text by the LLM / ActivityCard.
# NOTE: ``\b`` is intentionally only at the start. The trailing ``!`` in
# ``npm ERR!`` is a non-word char so ``ERR!\b`` would fail to match.
_ERROR_LINE_RE: Final[re.Pattern[str]] = re.compile(
    r"\b(?:ERROR|ERR!|FATAL|EXCEPTION|TRACEBACK|PANIC|"
    r"CRITICAL|SEGFAULT|ABORT)",
    re.IGNORECASE,
)


def try_parse_progress_line(line: str) -> dict[str, object] | None:
    """Best-effort parse of one stdout/stderr line into a notify payload."""
    if not line:
        return None

    explicit = _parse_explicit_marker(line)
    if explicit is not None:
        return explicit

    return _parse_heuristic(line)


def _parse_explicit_marker(line: str) -> dict[str, object] | None:
    """Recognise ``MYRM_PROGRESS`` / ``MYRM_CHECKPOINT`` JSON markers."""
    stripped = line.strip()
    if stripped.startswith(_MARKER_PROGRESS):
        body = stripped[len(_MARKER_PROGRESS) :].strip()
        payload = _safe_json(body)
        if payload is None:
            return None
        return _normalise_payload(payload, default_message="In progress")

    if stripped.startswith(_MARKER_CHECKPOINT):
        body = stripped[len(_MARKER_CHECKPOINT) :].strip()
        payload = _safe_json(body) or {}
        message = str(payload.get("message", "Checkpoint reached"))
        return {"message": message, "category": "background:checkpoint"}

    return None


def _safe_json(body: str) -> dict[str, object] | None:
    """Decode the marker body and ensure it is an object."""
    if not body:
        return {}
    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def _normalise_payload(payload: dict[str, object], *, default_message: str) -> dict[str, object]:
    """Map raw marker payload to a canonical notify dict."""
    result: dict[str, object] = {}

    raw_percent = payload.get("percent")
    if isinstance(raw_percent, int | float):
        result["progress"] = _clamp_percent(raw_percent)

    current = payload.get("current")
    total = payload.get("total")
    if isinstance(current, int | float) and isinstance(total, int | float) and total > 0:
        if "progress" not in result:
            result["progress"] = _clamp_percent(current / total * 100)
        result["step_index"] = int(current)
        result["total_steps"] = int(total)

    message = payload.get("message")
    if isinstance(message, str) and message.strip():
        result["message"] = message.strip()
    else:
        result["message"] = default_message

    return result


def _clamp_percent(value: float) -> int:
    """Clamp a percentage into the inclusive ``[0, 100]`` integer range."""
    return max(0, min(100, round(value)))


def _parse_heuristic(line: str) -> dict[str, object] | None:
    """Fallback for un-annotated tool output (npm, pytest, docker, ...).

    Lines flagged as errors are short-circuited so we never advertise an
    error report's percentage as build progress.
    """
    if _ERROR_LINE_RE.search(line):
        return None
    percent_match = _PERCENT_RE.search(line)
    if percent_match:
        percent = _clamp_percent(int(percent_match.group(1)))
        return {"progress": percent, "message": line.strip()[:160]}

    fraction_match = _FRACTION_RE.search(line)
    if fraction_match:
        current = float(fraction_match.group(1))
        total = float(fraction_match.group(2))
        if total > 0:
            payload: dict[str, object] = {
                "progress": _clamp_percent(current / total * 100),
                "message": line.strip()[:160],
            }
            # Only set step counters for integer counts (e.g. 3/10 tests, not 1.5/3.0 GiB).
            if current.is_integer() and total.is_integer():
                payload["step_index"] = int(current)
                payload["total_steps"] = int(total)
            return payload

    if _PHASE_RE.search(line):
        return {"message": line.strip()[:160]}

    return None


__all__ = ["try_parse_progress_line"]
