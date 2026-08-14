"""Dropped-constraint manifest builder for the context compaction pipeline.

[INPUT]
- langchain_core.messages::BaseMessage (POS: LangChain message base class)
- myrm_agent_harness.agent.security.detection.leak_detector::redact_leaks (POS: credential leak redaction)
- myrm_agent_harness.agent.security.detection.pii_redactor::redact_pii (POS: PII redaction for phone/email/SSN/ID/address)

[OUTPUT]
- build_dropped_manifest: pure function — extract short, sanitized constraint snippets
  that compaction evicted from the conversation window
- contains_constraint_marker: constraint-signal keyword matcher (shared by audit tooling)

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

# Constraint-signal keywords (Chinese + English). Detection is deliberately
# conservative: only text that looks like an explicit preference/directive is
# worth surfacing as "dropped". Conversational filler is ignored.
_CONSTRAINT_KEYWORDS: tuple[str, ...] = (
    # English — 短词覆盖长词的冗余项已剔除（如 "must" 已覆盖 "must not"）。
    "must",
    "never",
    "always",
    "do not",
    "don't",
    "remember",
    "important",
    "requirement",
    "ensure",
    "make sure",
    "should not",
    "shouldn't",
    "forbidden",
    "prohibited",
    "no need to",
    "avoid",
    "prefer",
    "rule",
    "constraint",
    "key point",
    "note that",
    "caution",
    "warning",
    # Chinese
    "不要",
    "别",
    "必须",
    "务必",
    "一定",
    "禁止",
    "切勿",
    "千万",
    "记住",
    "注意",
    "重要",
    "要求",
    "规则",
    "切记",
    "严格",
    "只能",
    "仅能",
    "确保",
    "请记得",
    "前提",
    "限制",
    "约束",
    "除非",
)


def contains_constraint_marker(content: str) -> bool:
    """Return whether a message carries an explicit constraint/preference signal.

    Keyword-based, deterministic, O(1) per candidate — no LLM, no network.
    Used to decide which evicted user messages deserve a spot in the
    dropped-constraint manifest.

    Args:
        content: Raw message text.

    Returns:
        True when the text contains a constraint keyword, else False.
    """
    lowered = content.lower()
    return any(keyword in lowered for keyword in _CONSTRAINT_KEYWORDS)


def _role_of(message: object) -> str:
    """Return a coarse role name for a LangChain message without heavy imports.

    Prefers the canonical ``BaseMessage.type`` attribute (works for every
    subclass including ``*MessageChunk``); falls back to the class name.
    """
    role = getattr(message, "type", None)
    if isinstance(role, str) and role in ("human", "ai", "system", "tool"):
        return role
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

        snippet = _sanitize_snippet(content)
        if not snippet:
            continue
        if snippet in seen:
            continue
        seen.add(snippet)
        dropped.append(snippet)
        if len(dropped) >= _MAX_MANIFEST_ITEMS:
            break

    return dropped


def _sanitize_snippet(content: str) -> str:
    """Redact + truncate a raw message into a safe audit snippet.

    Non-constraint content returns "" so the manifest stays focused on
    actionable lost instructions.
    """
    if not contains_constraint_marker(content):
        return ""

    redacted = redact_leaks(content)
    redacted, _ = redact_pii(redacted)
    return redacted[:_MAX_SNIPPET_CHARS]


__all__ = ["build_dropped_manifest", "contains_constraint_marker"]
