"""Dropped-constraint manifest builder for the context compaction pipeline.

[INPUT]
- langchain_core.messages::BaseMessage (POS: LangChain message base class)
- myrm_agent_harness.agent.security.detection.leak_detector::redact_leaks (POS: credential leak redaction)
- myrm_agent_harness.agent.security.detection.pii_redactor::redact_pii (POS: PII redaction for phone/email/SSN/ID/address)
- myrm_agent_harness.agent.security.detection.constraint_marker::contains_constraint_marker (POS: constraint signal detection)

[OUTPUT]
- build_dropped_manifest: pure function — extract short, sanitized constraint snippets
  that compaction evicted from the conversation window

[POS]
Fault-side attribution support (InteractionCentricFailureLocalizerStack):
when compaction removes user messages, any constraint-like content they carried
is recorded here (redacted + truncated). The GUI can then answer the question
"did compaction drop my constraint, or did the model ignore it?" — a Myrm
differentiator vs. competitors that offer no post-compaction attribution.

Zero-prompt-cost by design: the result is attached to StructuredSummary as
audit metadata and is excluded from to_json(), so it never inflates prompt-cache
payloads nor leaks pipeline internals into the model.
"""

from __future__ import annotations

from myrm_agent_harness.agent.security.detection.leak_detector import redact_leaks
from myrm_agent_harness.agent.security.detection.pii_redactor import redact_pii

# Message role constants (mirrors langchain_core.messages types without importing
# the heavyweight hierarchy in this hot audit path).
_ROLE_USER = "human"
_ROLE_SYSTEM = "system"

# Max number of constraint snippets retained per compaction. Keeps the event
# payload small while still giving the user a concrete sense of what was lost.
_MAX_MANIFEST_ITEMS = 3

# Per-snippet character budget after PII/credential redaction. Long instructions
# are prefixed with the signal word (the part that actually mattered).
_MAX_SNIPPET_CHARS = 160


def _role_of(message: object) -> str:
    """Return a coarse role name for a LangChain message without heavy imports."""
    type_name = type(message).__name__.lower()
    if type_name in ("humanmessage", "aimessage", "systemmessage", "toolmessage"):
        return type_name[:-7]  # human / ai / system / tool
    return type_name


def build_dropped_manifest(
    messages: list[object],
    protected_ids: set[int],
    recent_ids: set[int],
) -> list[str]:
    """Build a compact manifest of user constraints dropped by compaction.

    A message counts as "dropped" when it is a user (HumanMessage) message that
    survives neither the protected head nor the recent tail — i.e. its content
    was folded into the structured summary. We then keep only snippets that carry
    a constraint signal (e.g. "must", "never", "不要", "必须"), redact PII and
    credentials, truncate, and deduplicate.

    Pure function — no I/O, no LLM calls, no prompt tokens. Callers should pass
    the id() sets used to build the new message list.

    Args:
        messages: Full pre-compaction message list.
        protected_ids: id() of every message kept in the protected head.
        recent_ids: id() of every message kept in the recent tail.

    Returns:
        Up to ``_MAX_MANIFEST_ITEMS`` short constraint snippets, or [].
    """
    from myrm_agent_harness.agent.security.detection.constraint_marker import (
        contains_constraint_marker,
    )

    dropped: list[str] = []
    seen: set[str] = set()

    for message in messages:
        if _role_of(message) not in (_ROLE_USER, _ROLE_SYSTEM):
            continue
        if id(message) in protected_ids or id(message) in recent_ids:
            continue

        content = getattr(message, "content", None)
        if not isinstance(content, str) or not content.strip():
            continue

        snippet = _sanitize_snippet(content, contains_constraint_marker(content))
        if not snippet:
            continue
        if snippet in seen:
            continue
        seen.add(snippet)
        dropped.append(snippet)
        if len(dropped) >= _MAX_MANIFEST_ITEMS:
            break

    return dropped


def _sanitize_snippet(content: str, is_constraint: bool) -> str:
    """Redact + truncate a raw message into a safe audit snippet.

    For constraint-like content we retain a small head window (the signal usually
    lives at the start). For non-constraint content we return "" so the manifest
    stays focused on actionable lost instructions.
    """
    if not is_constraint:
        return ""

    redacted = redact_leaks(content)
    redacted, _ = redact_pii(redacted)
    return redacted[:_MAX_SNIPPET_CHARS]


__all__ = ["build_dropped_manifest"]
