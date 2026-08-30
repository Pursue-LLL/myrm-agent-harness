"""Memory auto-extraction — extract and persist memories from conversations.

[INPUT]
- toolkits.memory.manager::MemoryManager (POS: memory lifecycle manager)
- toolkits.memory.strategies.extractor::MemoryExtractor (POS: LLM-based memory extraction)
- toolkits.memory.types::ConversationMemory (POS: verbatim conversation type definition)
- toolkits.memory.chunking::chunk_conversation (POS: exchange-pair chunking strategy)
- agent.security.detection.deep_pii_detector::pseudonymize_deep_pii (POS: LLM deep PII detection)
- langchain_core::BaseChatModel (POS: LLM for extraction)
- utils.chat_utils::extract_answer_text (POS: LLM 响应答案提取 — 兼容 reasoning 模型 content 空回退)

[OUTPUT]
- build_extraction_messages(): Construct messages for extraction
- auto_extract_memories(): Dual-track extraction (verbatim + LLM, fire-and-forget)
- persist_extracted_memories(): Store LLM-extracted memories via MemoryManager
- create_conversation_memories(): Create verbatim ConversationMemory chunks
- create_extraction_llm_func(): LLM wrapper for MemoryExtractor

[POS]
Memory auto-extraction utilities. Implements dual-track extraction strategy:

**Dual-track extraction (MemPalace verbatim storage strategy):**
1. **Verbatim Track** (enable_verbatim=True, default): Raw exchange pairs stored
   as ConversationMemory (NO LLM processing, lossless preservation). Uses
   exchange-pair chunking: [(User Q1 + AI A1), (User Q2 + AI A2), ...].
   Dual-embedding (raw + summary vectors) enables adaptive dual-channel retrieval.

2. **Compressed Track**: LLM-extracted SemanticMemory/EpisodicMemory for context
   compression and efficiency.

**Deep PII protection** (when PrivacyPolicy.deep_scan=True):
After extraction, non-structured PII (medical conditions, political views, etc.)
is detected via LLM and pseudonymized through PseudonymStore before persistence.
Supplements the existing regex-based PII detection in memory_scanner.

**Invocation:** Called by SkillAgent at session end as fire-and-forget background
task (requires enable_memory_auto_extraction=True). Because the background task
runs after run-end cleanup cleared the privacy ContextVars, SkillAgent rebuilds
the security/policy/store context from its persisted SecurityConfig before
creating the task (see skill_agent/_privacy_context.py
``reestablish_privacy_context``), so extracted memories get the same PII
protection as in-run writes.

**Quality filter:** Trivial conversations (short replies or <=3 messages) are
skipped to save LLM calls, unless correction signals are detected.

**Configuration:**
- Framework layer (SkillAgent): enable_memory_auto_extraction (default True)
- Frontend: enableMemoryAutoExtraction UI toggle (Settings > Memory Section)
- Backend API: enable_memory_auto_extraction parameter passthrough
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Literal, Protocol

from langchain_core.language_models import BaseChatModel

from myrm_agent_harness.toolkits.memory.observability import MemoryOperationStatus
from myrm_agent_harness.utils.logger_utils import get_agent_logger

if TYPE_CHECKING:
    from langchain_core.messages import BaseMessage

    from myrm_agent_harness.toolkits.memory.manager import MemoryManager
    from myrm_agent_harness.toolkits.memory.strategies.extractor import ExtractedMemory


class ExtractionLifecycleObserver(Protocol):
    """Optional observer for per-turn memory write/extract visibility (GUI telemetry)."""

    async def __call__(
        self,
        phase: Literal["write", "extract"],
        status: MemoryOperationStatus,
        *,
        chat_id: str | None,
        summary: str,
        metadata: dict[str, str | int | float | bool | None] | None = None,
    ) -> None: ...


async def _notify_extraction_lifecycle(
    observer: ExtractionLifecycleObserver | None,
    phase: Literal["write", "extract"],
    status: MemoryOperationStatus,
    *,
    chat_id: str | None,
    summary: str,
    metadata: dict[str, str | int | float | bool | None] | None = None,
) -> None:
    if observer is None:
        return
    try:
        await observer(
            phase,
            status,
            chat_id=chat_id,
            summary=summary,
            metadata=metadata,
        )
    except Exception as exc:
        logger.debug("Extraction lifecycle observer failed: %s", exc)


from myrm_agent_harness.toolkits.memory.types import (  # noqa: E402 — deferred import to avoid circular dependency
    AnyMemory,
    ConversationMemory,
)
from myrm_agent_harness.utils.chat_utils import (  # noqa: E402 — deferred import to avoid circular dependency
    ChatHistoryReq,
    extract_answer_text,
)

logger = get_agent_logger(__name__)

_MIN_REPLY_LEN_FOR_EXTRACTION = 100


def build_extraction_messages(
    query: str | list[dict[str, object]],
    chat_history: ChatHistoryReq | list[BaseMessage] | None,
    assistant_reply: str,
) -> list[dict[str, str]]:
    """Construct messages for memory extraction (dict format)."""
    from myrm_agent_harness.utils.chat_utils import convert_chat_history_simple

    base_messages = convert_chat_history_simple(chat_history) if chat_history else []

    messages = [
        {
            "role": "assistant" if msg.type == "ai" else "user",
            "content": str(msg.content),
        }
        for msg in base_messages
    ]

    query_text = query if isinstance(query, str) else "[multimodal]"
    messages.append({"role": "user", "content": query_text})

    if assistant_reply:
        messages.append({"role": "assistant", "content": assistant_reply})

    return messages


def create_extraction_llm_func(
    llm: BaseChatModel,
) -> Callable[[str, str], Awaitable[str]]:
    """Create LLM function wrapper for MemoryExtractor."""
    from langchain_core.messages import HumanMessage, SystemMessage

    async def llm_func(system: str, prompt: str) -> str:
        msgs = (
            [SystemMessage(content=system), HumanMessage(content=prompt)] if system else [HumanMessage(content=prompt)]
        )
        resp = await llm.ainvoke(msgs)
        return extract_answer_text(resp)

    return llm_func


def create_conversation_memories(
    messages: list[dict[str, str]],
    source_chat_id: str | None = None,
    project_id: str | None = None,
    topic_id: str | None = None,
) -> list[ConversationMemory]:
    """Create verbatim ConversationMemory chunks from messages.

    Uses exchange-pair chunking (MemPalace strategy) to preserve completeness.

    Args:
        messages: List of dicts with 'role' and 'content' keys
        source_chat_id: Source chat/session identifier
        project_id: Project/wing hierarchy (optional)
        topic_id: Topic/room hierarchy (optional)

    Returns:
        List of ConversationMemory objects
    """
    from myrm_agent_harness.toolkits.memory.chunking import chunk_conversation
    from myrm_agent_harness.toolkits.memory.types import ConversationMemory

    chunks = chunk_conversation(messages)
    conversation_memories: list[ConversationMemory] = []

    for chunk in chunks:
        memory = ConversationMemory(
            raw_exchange=chunk.raw_text,
            content=chunk.user_turn,
            timestamp=chunk.timestamp,
            source_chat_id=source_chat_id,
            project_id=project_id,
            topic_id=topic_id,
            language=("zh" if any(ord(c) > 0x4E00 for c in chunk.user_turn[:50]) else "en"),
        )
        conversation_memories.append(memory)

    return conversation_memories


async def persist_extracted_memories(
    memories: list[ExtractedMemory],
    memory_manager: MemoryManager,
    source_chat_id: str | None,
    *,
    deep_scan_llm_func: Callable[[str, str], Awaitable[str]] | None = None,
    wiki_boundary_enabled: bool = False,
) -> int:
    """Persist extracted memories to MemoryManager.

    When *deep_scan_llm_func* is provided, non-structured PII in memory
    content is detected via LLM and pseudonymized before storage.

    Returns:
        Number of memories stored
    """
    from myrm_agent_harness.toolkits.memory.strategies.extractor import MemoryExtractor
    from myrm_agent_harness.toolkits.memory.types import ProfileEntry

    extractor = MemoryExtractor()
    concrete = extractor.to_concrete_memories(memories, source_chat_id=source_chat_id)
    if not concrete:
        return 0

    batch: list[AnyMemory] = []
    for mem in concrete:
        if isinstance(mem, ProfileEntry):
            await memory_manager.set_profile_attribute(mem.key, str(mem.value))
        else:
            batch.append(mem)

    if batch and deep_scan_llm_func is not None:
        batch = await _apply_deep_pii_scan(batch, deep_scan_llm_func, memory_manager)

    if batch and wiki_boundary_enabled:
        from myrm_agent_harness.toolkits.memory.wiki_memory_boundary import (
            filter_wiki_document_vector_memories,
        )

        filtered_batch, dropped = filter_wiki_document_vector_memories(batch, enabled=True)
        batch = filtered_batch
    else:
        dropped = 0

    if batch:
        from myrm_agent_harness.toolkits.memory.transient_fact_boundary import (
            filter_transient_business_memories,
        )

        filtered_transient_batch, dropped_transient = filter_transient_business_memories(batch)
        batch = filtered_transient_batch
        dropped += dropped_transient

    stored = await memory_manager.store_batch(batch) if batch else []
    return len(stored) + len(concrete) - len(batch) - dropped


async def _apply_deep_pii_scan(
    memories: list[AnyMemory],
    llm_func: Callable[[str, str], Awaitable[str]],
    memory_manager: MemoryManager,
) -> list[AnyMemory]:
    """Apply LLM-based deep PII detection and pseudonymization to memories.

    Batch-processes all memory contents in a single LLM call, then replaces
    detected non-structured PII with pseudonyms via PseudonymStore.
    """
    from myrm_agent_harness.agent.middlewares._session_context import (
        get_pseudonym_store,
    )
    from myrm_agent_harness.agent.security.detection.deep_pii_detector import (
        pseudonymize_deep_pii,
    )

    store = get_pseudonym_store()
    if store is None:
        logger.warning(
            "Deep PII scan skipped: PseudonymStore not available in this context "
            "(requires an enabled PrivacyPolicy with PSEUDONYMIZE or deep scan)"
        )
        return memories

    texts = [m.content for m in memories]
    real_name = await _get_user_real_name(memory_manager)

    try:
        results = await pseudonymize_deep_pii(texts, store, llm_func, real_name=real_name)
        for mem, result in zip(memories, results, strict=False):
            if result.items:
                mem.content = result.pseudonymized_text
    except Exception as e:
        logger.warning("Deep PII scan failed (non-fatal, regex fallback applies): %s", e)

    return memories


async def _get_user_real_name(memory_manager: MemoryManager) -> str:
    """Try to get user's real name from their profile for deep PII detection."""
    try:
        for key in ("name", "real_name", "full_name"):
            value = await memory_manager.get_profile_attribute(key)
            if value:
                return str(value)
    except Exception:
        pass
    return ""


async def auto_extract_memories(
    query: str | list[dict[str, object]],
    chat_history: ChatHistoryReq | list[BaseMessage] | None,
    memory_manager: MemoryManager,
    llm: BaseChatModel,
    extraction_llm: BaseChatModel | None = None,
    source_chat_id: str | None = None,
    assistant_reply: str = "",
    enable_verbatim: bool = True,
    *,
    deep_scan: bool = False,
    wiki_boundary_enabled: bool = False,
    lifecycle_observer: ExtractionLifecycleObserver | None = None,
) -> None:
    logger.info("auto_extract_memories invoked for %s", source_chat_id)
    try:
        from myrm_agent_harness.toolkits.memory.strategies.extractor import (
            ExtractionConfig,
            FeedbackSignal,
            detect_feedback_signals,
        )

        if not assistant_reply:
            return

        messages = build_extraction_messages(query, chat_history, assistant_reply)
        if len(messages) < 2:
            return

        feedback = detect_feedback_signals(messages)
        correction_detected = feedback == FeedbackSignal.NEGATIVE

        if feedback != FeedbackSignal.NONE:
            cited_ids = memory_manager.last_cited_memory_ids
            if cited_ids:
                memory_manager.set_last_cited_memory_ids([])
                score = 5 if feedback == FeedbackSignal.POSITIVE else 1
                rated = 0
                for mid in cited_ids:
                    try:
                        await memory_manager.rate_memory(mid, score)
                        rated += 1
                    except Exception:
                        logger.debug(
                            "Auto-rate skipped memory %s (not found or store error)",
                            mid,
                        )
                if rated:
                    logger.info(
                        "Auto-rated %d/%d cited memories (signal=%s, score=%d)",
                        rated,
                        len(cited_ids),
                        feedback.value,
                        score,
                    )

        if not correction_detected and len(assistant_reply) < _MIN_REPLY_LEN_FOR_EXTRACTION and len(messages) <= 3:
            logger.info("Skipping memory extraction: trivial conversation")
            await _notify_extraction_lifecycle(
                lifecycle_observer,
                "extract",
                MemoryOperationStatus.SKIPPED,
                chat_id=source_chat_id,
                summary="Skipped trivial conversation",
                metadata={"reason": "trivial"},
            )
            return

        await _notify_extraction_lifecycle(
            lifecycle_observer,
            "extract",
            MemoryOperationStatus.PENDING,
            chat_id=source_chat_id,
            summary="Memory extraction started",
        )

        verbatim_stored_count = 0

        if enable_verbatim:
            conversation_memories = create_conversation_memories(messages, source_chat_id=source_chat_id)
            if conversation_memories:
                stored_verbatim = await memory_manager.store_batch(conversation_memories)
                verbatim_stored_count = len(stored_verbatim)
                logger.info(
                    "Stored %d verbatim conversation chunks",
                    verbatim_stored_count,
                )
                await _notify_extraction_lifecycle(
                    lifecycle_observer,
                    "write",
                    MemoryOperationStatus.SUCCESS,
                    chat_id=source_chat_id,
                    summary=f"Stored {verbatim_stored_count} verbatim chunks",
                    metadata={"stored_count": verbatim_stored_count},
                )
            else:
                await _notify_extraction_lifecycle(
                    lifecycle_observer,
                    "write",
                    MemoryOperationStatus.SKIPPED,
                    chat_id=source_chat_id,
                    summary="No verbatim chunks to store",
                    metadata={"reason": "empty"},
                )
        else:
            await _notify_extraction_lifecycle(
                lifecycle_observer,
                "write",
                MemoryOperationStatus.SKIPPED,
                chat_id=source_chat_id,
                summary="Verbatim write disabled",
                metadata={"reason": "verbatim_disabled"},
            )

        llm_for_extraction = extraction_llm or llm
        llm_func = create_extraction_llm_func(llm_for_extraction)
        if correction_detected:
            logger.info("Correction signals detected in conversation, enhancing extraction prompt")
        config = ExtractionConfig(
            enable_task_digest=True,
            wiki_boundary_enabled=wiki_boundary_enabled,
        )

        from myrm_agent_harness.toolkits.memory.strategies.extractor import (
            extract_memories_from_conversation,
        )

        result = await extract_memories_from_conversation(
            messages,
            llm_func=llm_func,
            config=config,
            correction_detected=correction_detected,
        )

        if not result.memories:
            if verbatim_stored_count > 0:
                logger.info("Verbatim storage only: %d chunks", verbatim_stored_count)
            await _notify_extraction_lifecycle(
                lifecycle_observer,
                "extract",
                MemoryOperationStatus.SUCCESS,
                chat_id=source_chat_id,
                summary="Verbatim only — no compressed cards",
                metadata={
                    "verbatim_count": verbatim_stored_count,
                    "compressed_count": 0,
                },
            )
            return

        deep_scan_llm = llm_func if deep_scan else None
        stored_count = await persist_extracted_memories(
            result.memories,
            memory_manager,
            source_chat_id,
            deep_scan_llm_func=deep_scan_llm,
            wiki_boundary_enabled=wiki_boundary_enabled,
        )

        logger.info(
            "Auto-extracted %d memories, stored %d compressed + %d verbatim (%.0fms)",
            len(result.memories),
            stored_count,
            verbatim_stored_count,
            result.extraction_time_ms,
        )
        await _notify_extraction_lifecycle(
            lifecycle_observer,
            "extract",
            MemoryOperationStatus.SUCCESS,
            chat_id=source_chat_id,
            summary=f"Extracted {stored_count} memory cards",
            metadata={
                "stored_count": stored_count,
                "verbatim_count": verbatim_stored_count,
                "duration_ms": int(result.extraction_time_ms),
            },
        )
    except Exception as e:
        logger.warning("Memory auto-extraction failed (non-fatal): %s", e, exc_info=True)
        await _notify_extraction_lifecycle(
            lifecycle_observer,
            "extract",
            MemoryOperationStatus.ERROR,
            chat_id=source_chat_id,
            summary="Memory extraction failed",
            metadata={"error": type(e).__name__},
        )
