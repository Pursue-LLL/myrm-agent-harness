"""Approval-answer interpretation — the one reading of a human's HITL decision.

[INPUT]
- (none — pure decision interpretation, zero dependency)

[OUTPUT]
- is_approved: whether an ``interrupt()`` answer approves the gated action
- rejection_feedback: the human's own words for a denial, when they gave any
- APPROVE_WORDS: approval strings accepted from plain-text clients

[POS]
Foundation-layer SSOT for reading the value a client sends back into a LangGraph
``interrupt``. The gates that read an answer themselves — high-risk DOM and desktop
actions, privileged browser script, delegation batch/cognitive cost — read it here, so
the shapes the product actually sends are decided once and every other shape is a denial.
The tool-approval middleware keeps its own count-checked normalizer
(``agent/middlewares/approval/middleware.py``), which reads the same two shapes and is
fail-closed; consolidating it onto this module is a separate change.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping

logger = logging.getLogger(__name__)

APPROVE_WORDS: frozenset[str] = frozenset({"approve", "allow", "yes", "y"})
"""Approval strings a plain-text client may answer with (IM text reply, harness CLI)."""

_APPROVED_TYPES: frozenset[str] = frozenset({"approve", "edit"})
"""Decision types that let the action through; ``edit`` approves with modified arguments."""


def _decision_entry_type(entry: object) -> str | None:
    """The ``type`` of one batch decision entry, ``None`` when the entry cannot carry an approval."""
    if isinstance(entry, Mapping):
        decision = entry.get("type")
        return decision if isinstance(decision, str) else None
    logger.warning("HITL decision entry is not an object, read as a denial: %.80r", entry)
    return None


def _batch_entries(answer: Mapping[str, object]) -> list[object] | None:
    """The entries of a batch answer (``{"decisions": [...]}``); ``None`` when the answer is not one."""
    entries = answer.get("decisions")
    return list(entries) if isinstance(entries, list) else None


def is_approved(user_response: object) -> bool:
    """Whether ``user_response`` approves the interrupted action. Anything unrecognized denies it.

    Two answer shapes are produced by the product's clients: one decision for the whole
    pause (``{"decision": "approve" | "reject"}``, sent by the WebUI approval drawer and the
    HITL timer) and one decision per requested item (``{"decisions": [{"type": ...}, ...]}``,
    sent by the chat tool-approval card, the drawer's subagent batch and the IM buttons).
    A batch answer approves only when every entry approves.
    """
    if isinstance(user_response, Mapping):
        entries = _batch_entries(user_response)
        if entries is not None:
            return bool(entries) and all(_decision_entry_type(entry) in _APPROVED_TYPES for entry in entries)
        return user_response.get("decision") in _APPROVED_TYPES
    if isinstance(user_response, str):
        return user_response.lower() in APPROVE_WORDS
    logger.warning("Unrecognized HITL answer shape, read as a denial: %.80r", user_response)
    return False


def rejection_feedback(user_response: object) -> str:
    """The human's own reason for a denial, when they gave one.

    Reads the two shapes the product's clients produce: one decision for the whole pause
    (``{"decision": "reject", "feedback" | "guidance": "<words>"}``) and one decision per
    requested item (``{"decisions": [{"type": "reject", ...}, ...]}``, first entry with words).

    ``guidance`` is read first — the IM ``/deny <reason>`` sender always fills ``feedback``
    with its own generic line (``Denied via <channel> channel command``) and puts the
    person's words in ``guidance`` — and ``feedback`` is the fallback for every other client,
    which sends no ``guidance``. Blank and whitespace-only values are not a reason: they never
    reach the model, and a ``guidance`` of only spaces falls through to the real ``feedback``.
    """
    if not isinstance(user_response, Mapping):
        return ""
    for key in ("guidance", "feedback"):
        value = user_response.get(key)
        text = value.strip() if isinstance(value, str) else ""
        if text:
            return text
    for entry in _batch_entries(user_response) or ():
        text = rejection_feedback(entry)
        if text:
            return text
    return ""
