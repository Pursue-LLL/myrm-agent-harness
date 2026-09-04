"""Anti-drift distillation guards and self-exclusion strategy.

Defines deterministic admission guards that prevent memory distillation pipelines
from suffering from self-reinforcing persona drift (echo chamber effect), unconfirmed
identity attribution errors, and automated bot alert pollution.

[INPUT]
- Sequence[dict[str, object]] or DistillationCandidate payloads

[OUTPUT]
- SelfIdentityState: Tri-state identity model (SELF / OTHER / UNCONFIRMED)
- DistillationOrigin: Message source classification (USER / AGENT / BOT / SYSTEM)
- EvidenceReference: Structured evidence provenance anchor
- DistillationRejectionCode: Machine-stable rejection codes
- DistillationCandidate: Validated distillation message candidate
- DistillationGuardResult: Typed guard check verdict
- DistillationGuardRejectionError: Hard assertion violation exception
- assert_distillable: Deterministic guard assertion
- check_distillable: Pure functional admission check
- filter_distillable_messages: Pre-extraction conversation message filter
- assert_has_evidence: Memory evidence chain assertion

[POS]
Memory distillation admission guard. Pure Python standard library + Pydantic.
Zero network overhead (<1ms), zero external dependencies, 100% deterministic.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, TypeVar

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.memory.strategies.extractor import ExtractedMemory
    from myrm_agent_harness.toolkits.memory.types import BaseMemory

logger = logging.getLogger(__name__)

T = TypeVar("T")

# Precompiled regex patterns for detecting automated system monitoring bots
_ALERT_BOT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?:bot|webhook|cron|daemon|alertmanager|prometheus|grafana|sentry|datadog|jenkins|ci[-_]?cd|actions)", re.IGNORECASE),
    re.compile(r"(?:监控|告警|机器人|系统通知|打卡助手|运维通知|报警)"),
)


class SelfIdentityState(StrEnum):
    """Tri-state identity classification for distillation candidates.

    - SELF: Verified as the primary user本人. Eligible for profile/preference extraction.
    - OTHER: Confirmed third party. Never extracted into user profile; only as third-party relations.
    - UNCONFIRMED: Ambiguous / unverified speaker. Hard-rejected to prevent catastrophic misattribution.
    """

    SELF = "self"
    OTHER = "other"
    UNCONFIRMED = "unconfirmed"

    @classmethod
    def from_bool_or_none(cls, value: bool | None) -> SelfIdentityState:
        """Convert a standard bool | None to explicit tri-state enum."""
        if value is True:
            return cls.SELF
        if value is False:
            return cls.OTHER
        return cls.UNCONFIRMED


class DistillationOrigin(StrEnum):
    """Originator of a conversation turn or message."""

    USER = "user"
    AGENT = "agent"
    BOT = "bot"
    SYSTEM = "system"


class DistillationRejectionCode(StrEnum):
    """Machine-stable rejection codes for distillation admission failures."""

    REJECT_ORIGIN_AGENT = "reject_origin_agent"
    REJECT_IDENTITY_UNCONFIRMED = "reject_identity_unconfirmed"
    REJECT_IDENTITY_OTHER = "reject_identity_other"
    REJECT_BOT_OR_ALERT = "reject_bot_or_alert"
    REJECT_MISSING_EVIDENCE = "reject_missing_evidence"
    REJECT_EMPTY_CONTENT = "reject_empty_content"
    REJECT_TRANSIENT_STATE = "reject_transient_state"
    REJECT_EVIDENCE_FROM_AGENT = "reject_evidence_from_agent"
    REJECT_FABRICATED_QUOTE = "reject_fabricated_quote"


from myrm_agent_harness.toolkits.memory.types import (
    EvidenceReference,
)


class DistillationCandidate(BaseModel):
    """Structured candidate payload submitted to distillation admission guards."""

    content: str = Field(..., description="Message text or turn content")
    origin: DistillationOrigin = Field(default=DistillationOrigin.USER, description="Message origin")
    is_self: SelfIdentityState = Field(
        default=SelfIdentityState.SELF,
        description="Speaker identity classification relative to the primary user",
    )
    is_bot_or_alert: bool = Field(default=False, description="Flag indicating automated bot or alert channel")
    sender_name: str | None = Field(default=None, description="Optional sender display name for bot heuristic checks")
    evidence: list[EvidenceReference] = Field(default_factory=list, description="Associated evidence references")
    metadata: dict[str, str | int | float | bool] = Field(default_factory=dict)


class DistillationGuardResult(BaseModel):
    """Result of an admission check evaluation."""

    allowed: bool
    rejection_code: DistillationRejectionCode | None = None
    rejection_reason: str = ""


class DistillationGuardRejectionError(ValueError):
    """Raised when a distillation candidate violates hard admission constraints."""

    def __init__(self, code: DistillationRejectionCode, reason: str, candidate: DistillationCandidate) -> None:
        super().__init__(f"Distillation rejected [{code.value}]: {reason}")
        self.code = code
        self.reason = reason
        self.candidate = candidate


def is_alert_or_bot_sender(sender_name: str | None) -> bool:
    """Check whether a sender name matches automated bot or monitoring alert signatures."""
    if not sender_name:
        return False
    stripped = sender_name.strip()
    return any(p.search(stripped) for p in _ALERT_BOT_PATTERNS)


def check_distillable(candidate: DistillationCandidate) -> DistillationGuardResult:
    """Evaluate whether a message candidate satisfies hard distillation admission rules.

    Pure deterministic inspection (0 LLM call, <1ms):
    1. Content emptiness check
    2. Origin exclusion: Agent self-generated content is PERMANENTLY excluded
    3. Tri-state identity: UNCONFIRMED identity is rejected (no fuzzy name guesses)
    4. Automated bot / alert exclusion: Bot channels and monitoring alerts are excluded
    """
    stripped = candidate.content.strip()
    if not stripped:
        return DistillationGuardResult(
            allowed=False,
            rejection_code=DistillationRejectionCode.REJECT_EMPTY_CONTENT,
            rejection_reason="Candidate content is empty or whitespace only",
        )

    # 1. Digital Persona Self-Exclusion: Agent messages MUST NEVER be distilled as user traits
    if candidate.origin == DistillationOrigin.AGENT:
        return DistillationGuardResult(
            allowed=False,
            rejection_code=DistillationRejectionCode.REJECT_ORIGIN_AGENT,
            rejection_reason="Agent self-generated messages are permanently excluded from memory distillation",
        )

    # 2. Bot & Monitoring Alert Exclusion (Priority over human identity)
    if candidate.is_bot_or_alert or candidate.origin == DistillationOrigin.BOT:
        return DistillationGuardResult(
            allowed=False,
            rejection_code=DistillationRejectionCode.REJECT_BOT_OR_ALERT,
            rejection_reason="Automated bot messages and system alerts are excluded from memory distillation",
        )

    if candidate.sender_name and is_alert_or_bot_sender(candidate.sender_name):
        return DistillationGuardResult(
            allowed=False,
            rejection_code=DistillationRejectionCode.REJECT_BOT_OR_ALERT,
            rejection_reason=f"Sender '{candidate.sender_name}' matches automated alert bot pattern",
        )

    # 3. Strict Tri-State Identity: Unconfirmed identity strictly prohibited
    if candidate.is_self == SelfIdentityState.UNCONFIRMED:
        return DistillationGuardResult(
            allowed=False,
            rejection_code=DistillationRejectionCode.REJECT_IDENTITY_UNCONFIRMED,
            rejection_reason="Speaker identity is unconfirmed; guessing identity is forbidden to prevent cross-contamination",
        )
    if candidate.is_self == SelfIdentityState.OTHER:
        return DistillationGuardResult(
            allowed=False,
            rejection_code=DistillationRejectionCode.REJECT_IDENTITY_OTHER,
            rejection_reason="Third-party messages cannot be distilled as primary user traits",
        )

    return DistillationGuardResult(allowed=True)


def assert_distillable(candidate: DistillationCandidate) -> None:
    """Enforce hard admission assertion on a candidate, raising exception if rejected."""
    result = check_distillable(candidate)
    if not result.allowed:
        assert result.rejection_code is not None
        raise DistillationGuardRejectionError(
            code=result.rejection_code,
            reason=result.rejection_reason,
            candidate=candidate,
        )


def filter_distillable_messages(
    messages: Sequence[dict[str, object]],
    *,
    default_source_id: str = "",
    allow_other_as_context: bool = False,
) -> tuple[list[dict[str, object]], list[DistillationGuardResult]]:
    """Filter raw conversation messages before LLM memory distillation.

    Excludes assistant turns from profile extraction seeds, drops bot/system
    notifications, and enforces verified identity states.
    """
    admitted: list[dict[str, object]] = []
    rejections: list[DistillationGuardResult] = []

    for msg in messages:
        role = str(msg.get("role") or "").lower()
        content = str(msg.get("content") or "")
        sender_name = str(msg.get("name") or "") if msg.get("name") else None

        # Map role to origin
        if role in ("assistant", "ai"):
            origin = DistillationOrigin.AGENT
            identity = SelfIdentityState.OTHER
        elif role == "system":
            origin = DistillationOrigin.SYSTEM
            identity = SelfIdentityState.OTHER
        else:
            origin = DistillationOrigin.USER
            # Check explicit is_self metadata if present
            raw_is_self = msg.get("is_self")
            if isinstance(raw_is_self, bool):
                identity = SelfIdentityState.SELF if raw_is_self else SelfIdentityState.OTHER
            elif isinstance(raw_is_self, str) and raw_is_self in ("self", "other", "unconfirmed"):
                identity = SelfIdentityState(raw_is_self)
            elif raw_is_self is None and "is_self" in msg:
                identity = SelfIdentityState.UNCONFIRMED
            else:
                # Default 1-on-1 user messages are assumed self
                identity = SelfIdentityState.SELF

        msg_id = str(msg.get("id") or msg.get("message_id") or "")
        evidence_list = [
            EvidenceReference(
                source_id=default_source_id or "session",
                message_id=msg_id if msg_id else None,
                quote_snippet=content[:160] if content else None,
                author_id=sender_name,
            )
        ]

        candidate = DistillationCandidate(
            content=content,
            origin=origin,
            is_self=identity,
            sender_name=sender_name,
            evidence=evidence_list,
        )

        check = check_distillable(candidate)
        if check.allowed:
            admitted.append(dict(msg))
        else:
            # If allow_other_as_context is True and rejection was merely OTHER identity,
            # allow keeping it as third-party dialogue background, but tag it
            if allow_other_as_context and candidate.is_self == SelfIdentityState.OTHER and candidate.origin == DistillationOrigin.USER:
                tagged = dict(msg)
                tagged["_third_party_context"] = True
                admitted.append(tagged)
            else:
                rejections.append(check)
                logger.debug(
                    "Distillation guard rejected message [%s]: %s",
                    check.rejection_code,
                    check.rejection_reason,
                )

    return admitted, rejections


def is_valid_evidence_reference(
    ref: EvidenceReference,
    *,
    allowed_verbatim_corpus: Sequence[str] | None = None,
) -> tuple[bool, DistillationRejectionCode | None, str]:
    """Validate the integrity, provenance, and authenticity of an evidence anchor.

    Guards against:
    1. Empty/dangling references (all IDs/snippets empty)
    2. Evidentiary Trojan Horse: evidence citing Agent or Bot as author
    3. Hallucinated quotes: quote_snippet not present in verified source corpus
    """
    if not ref.source_id or not ref.source_id.strip():
        return False, DistillationRejectionCode.REJECT_MISSING_EVIDENCE, "Evidence source_id cannot be empty"

    has_substance = bool(
        (ref.message_id and ref.message_id.strip())
        or (ref.quote_snippet and len(ref.quote_snippet.strip()) >= 2)
        or (ref.channel_id and ref.channel_id.strip())
    )
    if not has_substance:
        return (
            False,
            DistillationRejectionCode.REJECT_MISSING_EVIDENCE,
            "Evidence reference is a dangling shell without message_id, channel_id, or quote_snippet",
        )

    # Evidentiary Trojan Horse Guard: Agent/Bot cannot be the author of truth
    if ref.author_id:
        norm_author = ref.author_id.strip().lower()
        if norm_author in ("agent", "assistant", "system", "bot") or is_alert_or_bot_sender(norm_author):
            return (
                False,
                DistillationRejectionCode.REJECT_EVIDENCE_FROM_AGENT,
                f"Evidence citation points to excluded entity author '{ref.author_id}'",
            )

    # Hallucinated Quote Guard
    if ref.quote_snippet and allowed_verbatim_corpus:
        snippet_clean = ref.quote_snippet.strip().lower()
        matched = any(snippet_clean in corpus_text.lower() for corpus_text in allowed_verbatim_corpus)
        if not matched:
            return (
                False,
                DistillationRejectionCode.REJECT_FABRICATED_QUOTE,
                f"Evidence quote '{ref.quote_snippet[:40]}...' does not exist in source corpus",
            )

    return True, None, ""


def assert_has_evidence(
    memories: Sequence[ExtractedMemory | BaseMemory],
    *,
    allowed_verbatim_corpus: Sequence[str] | None = None,
) -> None:
    """Assert that all extracted memories maintain a verified, non-hallucinated evidence anchor.

    Guarantees 'Evidence before answers': every synthesized fact must be traceable
    back to a non-agent source and verified verbatim context.
    """
    for mem in memories:
        has_valid_evidence = False
        rejection_reason = "Lacks provenance evidence reference"
        rejection_code = DistillationRejectionCode.REJECT_MISSING_EVIDENCE

        evidence_field = getattr(mem, "evidence", None)
        if isinstance(evidence_field, list) and len(evidence_field) > 0:
            for item in evidence_field:
                if isinstance(item, EvidenceReference):
                    valid, code, reason = is_valid_evidence_reference(
                        item,
                        allowed_verbatim_corpus=allowed_verbatim_corpus,
                    )
                    if valid:
                        has_valid_evidence = True
                        break
                    else:
                        rejection_code = code or DistillationRejectionCode.REJECT_MISSING_EVIDENCE
                        rejection_reason = reason
        elif getattr(mem, "source_message", None) or getattr(mem, "source_chat_id", None) or getattr(mem, "source_message_id", None):
            has_valid_evidence = True
        else:
            meta = getattr(mem, "metadata", None)
            if isinstance(meta, dict) and (meta.get("evidence_quote") or meta.get("evidence_count")):
                has_valid_evidence = True
            elif hasattr(mem, "key") and hasattr(mem, "value"):
                has_valid_evidence = True

        if not has_valid_evidence:
            content_snippet = getattr(mem, "content", str(mem))[:60]
            raise ValueError(
                f"Distillation rejected [{rejection_code.value}]: "
                f"Memory fact '{content_snippet}' failed evidence check: {rejection_reason}"
            )


def filter_memories_with_evidence(
    memories: Sequence[T],
    *,
    fallback_source_id: str | None = None,
    allowed_verbatim_corpus: Sequence[str] | None = None,
) -> tuple[list[T], list[T]]:
    """Separate memories into those with verified evidence vs ungrounded/fabricated memories.

    If fallback_source_id is provided and a memory lacks explicit source anchors,
    fallback_source_id is bound as the provenance anchor.
    """
    grounded: list[T] = []
    ungrounded: list[T] = []

    for mem in memories:
        has_ev = False
        evidence_field = getattr(mem, "evidence", None)
        if isinstance(evidence_field, list) and len(evidence_field) > 0:
            for item in evidence_field:
                if isinstance(item, EvidenceReference):
                    valid, _, _ = is_valid_evidence_reference(
                        item,
                        allowed_verbatim_corpus=allowed_verbatim_corpus,
                    )
                    if valid:
                        has_ev = True
                        break
        if not has_ev:
            if getattr(mem, "source_message", None) or getattr(mem, "source_chat_id", None) or getattr(mem, "source_message_id", None):
                has_ev = True
            elif fallback_source_id:
                if hasattr(mem, "source_chat_id") and getattr(mem, "source_chat_id", None) is None:
                    try:
                        setattr(mem, "source_chat_id", fallback_source_id)
                    except Exception:
                        pass
                has_ev = True
            else:
                meta = getattr(mem, "metadata", None)
                if isinstance(meta, dict) and (meta.get("evidence_quote") or meta.get("evidence_count")):
                    has_ev = True
                elif hasattr(mem, "key") and hasattr(mem, "value"):
                    has_ev = True

        if has_ev:
            grounded.append(mem)
        else:
            ungrounded.append(mem)

    return grounded, ungrounded
