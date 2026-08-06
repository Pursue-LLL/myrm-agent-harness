"""Chat message → Wiki pending compound staging (zero LLM).

[INPUT]
..core.section_contract (POS: Compiled Truth / Timeline skeleton)
..core.frontmatter_contract (POS: session frontmatter + metadata)
..core.claims_contract (POS: structured claims merge)
..pending.WikiPendingEditsManager (POS: HITL stage SSOT)

[OUTPUT]
build_chat_compound_draft: assemble pending markdown from Q&A + trust signals
stage_chat_compound: dedupe by source_message + stage_pending_edit

[POS]
REST/chat capture pipeline only. Agent auto-archive uses publish_raw separately.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from myrm_agent_harness.toolkits.wiki.core.claims_contract import (
    WikiClaim,
    ensure_compile_claims,
    merge_claims_into_content,
    parse_claims_from_content,
)
from myrm_agent_harness.toolkits.wiki.core.frontmatter_contract import (
    WikiPageType,
    WikiProvenance,
    ensure_frontmatter_type,
    load_frontmatter_metadata,
    serialize_frontmatter_block,
)
from myrm_agent_harness.toolkits.wiki.core.section_contract import build_note_body_skeleton
from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure
from myrm_agent_harness.toolkits.wiki.pipeline.pending import WikiPendingEditsManager
from myrm_agent_harness.toolkits.wiki.retrieval.indexer import WikiIndexer

CHAT_COMPOUND_PROVENANCE = "chat-compound"
_COVERAGE_DISCLAIMER = (
    "> **Coverage note:** This draft is not backed by verified wiki evidence. "
    "Review before approving."
)


@dataclass(frozen=True, slots=True)
class ChatCompoundTrustContext:
    has_knowledge_sources: bool
    has_verified_snapshot: bool


@dataclass(frozen=True, slots=True)
class ChatCompoundRequest:
    concept_name: str
    user_question: str
    assistant_answer: str
    source_chat: str
    source_message: str
    trust: ChatCompoundTrustContext


@dataclass(frozen=True, slots=True)
class ChatCompoundResult:
    pending_edit_id: int
    concept_name: str


@dataclass(frozen=True, slots=True)
class ChatCompoundError(Exception):
    """Structured chat compound failure for REST callers."""

    code: str
    message: str

    def __str__(self) -> str:
        return self.message


def _utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _format_qa_compiled_truth(
    *,
    user_question: str,
    assistant_answer: str,
    trust: ChatCompoundTrustContext,
) -> str:
    sections: list[str] = []
    if not trust.has_verified_snapshot:
        sections.append(_COVERAGE_DISCLAIMER)
    sections.append(f"# Query\n\n{user_question.strip()}")
    sections.append(f"# Answer\n\n{assistant_answer.strip()}")
    return "\n\n".join(sections)


def _apply_trust_claim_status(content: str, *, trust: ChatCompoundTrustContext) -> str:
    claims = parse_claims_from_content(content)
    if not claims:
        return content
    claim_status = "supported" if trust.has_verified_snapshot else "unsupported"
    updated: list[WikiClaim] = [
        WikiClaim(
            id=claim.id,
            text=claim.text,
            status=claim_status,
            confidence=claim.confidence,
            evidence=claim.evidence,
            updated_at=_utc_now_iso(),
        )
        for claim in claims
    ]
    return merge_claims_into_content(content, tuple(updated))


def build_chat_compound_draft(
    structure: WikiStructure,
    request: ChatCompoundRequest,
) -> str:
    """Build pending-review markdown for a chat Q&A compound draft."""
    concept_name = request.concept_name.strip()
    if not concept_name:
        raise ChatCompoundError("invalid_request", "concept_name is required")
    answer = request.assistant_answer.strip()
    if not answer:
        raise ChatCompoundError("invalid_request", "assistant_answer is required")

    question = request.user_question.strip() or "(No preceding user message captured)"
    compiled_truth = _format_qa_compiled_truth(
        user_question=question,
        assistant_answer=answer,
        trust=request.trust,
    )
    timeline_entry = f"Staged from chat compound at {_utc_now_iso()}"
    body = build_note_body_skeleton(compiled_truth=compiled_truth, timeline_entry=timeline_entry)
    page_type = WikiPageType.SESSION
    content = ensure_frontmatter_type(
        body,
        page_type,
        sources=[concept_name],
        provenance=WikiProvenance.CHAT_COMPOUND,
    )
    metadata, body_only = load_frontmatter_metadata(content)
    metadata["source_chat"] = request.source_chat.strip()
    metadata["source_message"] = request.source_message.strip()
    metadata["compound_provenance"] = CHAT_COMPOUND_PROVENANCE
    content = serialize_frontmatter_block(metadata) + body_only.lstrip("\n")
    content = ensure_compile_claims(content, concept_name, [concept_name], structure=structure)
    return _apply_trust_claim_status(content, trust=request.trust)


def find_pending_edit_id_by_source_message(
    pending_mgr: WikiPendingEditsManager,
    source_message: str,
) -> int | None:
    """Return pending edit id when the same chat message was already staged."""
    needle = source_message.strip()
    if not needle:
        return None
    for edit in pending_mgr.get_pending_edits(limit=200):
        proposed = str(edit.get("proposed_content") or "")
        if not proposed:
            continue
        metadata, _ = load_frontmatter_metadata(proposed)
        if str(metadata.get("source_message") or "").strip() == needle:
            edit_id = edit.get("id")
            if isinstance(edit_id, int):
                return edit_id
    return None


async def stage_chat_compound(
    structure: WikiStructure,
    indexer: WikiIndexer | None,
    pending_mgr: WikiPendingEditsManager,
    request: ChatCompoundRequest,
) -> ChatCompoundResult:
    """Stage a chat Q&A compound draft into the pending edits queue."""
    source_message = request.source_message.strip()
    if not source_message:
        raise ChatCompoundError("invalid_request", "source_message is required")

    existing_id = find_pending_edit_id_by_source_message(pending_mgr, source_message)
    if existing_id is not None:
        raise ChatCompoundError(
            "already_staged",
            f"Chat message already staged as pending edit {existing_id}",
        )

    draft = build_chat_compound_draft(structure, request)
    edit_id = await pending_mgr.stage_pending_edit(
        request.concept_name.strip(),
        draft,
        provenance=CHAT_COMPOUND_PROVENANCE,
    )
    return ChatCompoundResult(pending_edit_id=edit_id, concept_name=request.concept_name.strip())
