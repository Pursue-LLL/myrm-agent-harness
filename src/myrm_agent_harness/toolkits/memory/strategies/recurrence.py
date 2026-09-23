"""Recurrence-triggered memory consolidation strategy.


[INPUT]
- memory.config::RecurrenceConfig (POS: recurrence detection configuration)
- memory.protocols.embedding::EmbeddingProtocol (POS: text to vector)
- memory.protocols.vector::VectorStoreProtocol (POS: vector storage)

[OUTPUT]
- RecurrenceDetector: Detects recurrent topics across sessions and triggers LLM consolidation.
- RecurrenceResult: Detection result with triggered flag and consolidated content.

[POS]
Recurrence-triggered memory consolidation. Detects topics that appear repeatedly across
sessions via embedding similarity, then triggers LLM refinement to produce high-quality
long-term memories. Includes an importance-preemption bypass for safety/health/identity
signals that consolidate immediately on first occurrence.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from myrm_agent_harness.toolkits.memory.protocols.embedding import EmbeddingProtocol
from myrm_agent_harness.toolkits.memory.protocols.vector import (
    VectorDocument,
    VectorStoreProtocol,
)

logger = logging.getLogger(__name__)

LLMFunc = Callable[[str, str], Awaitable[str]]

_RECURRENCE_COLLECTION_SUFFIX = "_recurrence_buffer"

_IMPORTANCE_KEYWORDS_EN = frozenset(
    {
        "allergy",
        "allergic",
        "anaphylaxis",
        "medication",
        "prescription",
        "diabetes",
        "asthma",
        "epilepsy",
        "emergency",
        "hospital",
        "password",
        "credential",
        "deadline",
        "urgent",
        "phobia",
        "trauma",
        "intolerance",
        "wheelchair",
        "disability",
    }
)

_IMPORTANCE_KEYWORDS_CN = frozenset(
    {
        "过敏",
        "药物",
        "处方",
        "糖尿病",
        "哮喘",
        "癫痫",
        "急诊",
        "医院",
        "密码",
        "密钥",
        "凭证",
        "截止日期",
        "紧急",
        "恐惧",
        "创伤",
        "饮食禁忌",
        "不耐受",
        "残疾",
        "轮椅",
    }
)

_TRIVIAL_SUMMARY_PATTERNS = frozenset(
    {
        "hello",
        "hi",
        "hey",
        "hi there",
        "hello there",
        "greetings",
        "good morning",
        "good afternoon",
        "good evening",
        "morning",
        "ok",
        "okay",
        "fine",
        "cool",
        "sure",
        "thanks",
        "thank you",
        "thanks a lot",
        "thank you very much",
        "thx",
        "bye",
        "goodbye",
        "test",
        "testing",
        "ping",
        "pong",
        "chat",
        "你好",
        "您好",
        "你好呀",
        "在吗",
        "在不在",
        "打个招呼",
        "问好",
        "测试",
        "哈喽",
        "嗨",
        "好的",
        "好的收到",
        "收到",
        "明白",
        "行",
        "可以",
        "谢谢",
        "多谢",
        "再见",
        "拜拜",
    }
)

_CONSOLIDATION_SYSTEM_PROMPT = """\
You are a memory consolidation specialist. Given multiple conversation snippets \
where the user repeatedly discussed the same topic, synthesize a single concise \
long-term memory entry.

Rules:
- Output ONLY the consolidated memory text (1-3 sentences)
- Capture the user's actual preference/fact/habit, not the conversation context
- Use the same language as the user's messages
- Be specific and actionable (e.g. "User prefers Python for data tasks" not "User discusses programming")
- If snippets contain contradictions, use the most recent information
"""


@dataclass(frozen=True, slots=True)
class RecurrenceResult:
    """Result of recurrence detection for a session."""

    triggered: bool
    consolidated_content: str | None = None
    recurrence_count: int = 0
    topic_summary: str | None = None


class RecurrenceDetector:
    """Detects recurrent topics across sessions and produces consolidated memories.

    Uses a dedicated vector collection as a lightweight ring buffer: each session's
    summary embedding is stored, and on each new session end, similarity search
    identifies whether the topic has appeared >= k times (recurrence threshold).

    When triggered, an LLM call produces a refined memory from the accumulated snippets.
    """

    def __init__(
        self,
        *,
        embedding: EmbeddingProtocol,
        vector: VectorStoreProtocol,
        collection_prefix: str,
        similarity_threshold: float = 0.70,
        recurrence_k: int = 4,
        buffer_capacity: int = 200,
        importance_preemption: bool = True,
        soft_deprecation: bool = True,
    ) -> None:
        self._embedding = embedding
        self._vector = vector
        self._collection = f"{collection_prefix}{_RECURRENCE_COLLECTION_SUFFIX}"
        self._similarity_threshold = similarity_threshold
        self._recurrence_k = recurrence_k
        self._buffer_capacity = buffer_capacity
        self._importance_preemption = importance_preemption
        self._soft_deprecation = soft_deprecation
        self._initialized = False

    async def _ensure_collection(self) -> None:
        if self._initialized:
            return
        await self._vector.ensure_collection(
            self._collection,
            self._embedding.dimension,
            distance="cosine",
        )
        self._initialized = True

    async def check_recurrence(
        self,
        session_summary: str,
        *,
        llm_func: LLMFunc | None = None,
    ) -> RecurrenceResult:
        """Check if this session's topic recurs across previous sessions.

        Args:
            session_summary: A concise summary of the current session's key topics.
            llm_func: Optional LLM call for consolidation (system_prompt, user_prompt) -> response.

        Returns:
            RecurrenceResult indicating whether consolidation was triggered.
        """
        if not session_summary.strip():
            return RecurrenceResult(triggered=False)

        if self._importance_preemption and _is_important(session_summary):
            return RecurrenceResult(
                triggered=True,
                consolidated_content=session_summary,
                recurrence_count=1,
                topic_summary="importance_preemption",
            )

        if _is_trivial_summary(session_summary):
            return RecurrenceResult(
                triggered=False,
                recurrence_count=0,
                topic_summary="trivial_filtered",
            )

        await self._ensure_collection()

        query_vec = await self._embedding.embed(session_summary)

        similar = await self._vector.search(
            self._collection,
            query_vec,
            limit=self._recurrence_k + 10,
            score_threshold=self._similarity_threshold,
        )

        similar_active = [
            r for r in similar
            if not r.document.metadata.get("is_deprecated")
        ]

        recurrence_count = len(similar_active) + 1  # +1 for current session

        doc_id = str(uuid.uuid4())
        now_iso = datetime.now(UTC).isoformat()
        await self._vector.upsert(
            self._collection,
            [
                VectorDocument(
                    id=doc_id,
                    content=session_summary,
                    vector=query_vec,
                    metadata={"created_at": now_iso, "is_deprecated": False},
                )
            ],
        )

        await self._evict_old_entries()

        if recurrence_count < self._recurrence_k:
            return RecurrenceResult(
                triggered=False,
                recurrence_count=recurrence_count,
            )

        snippets = [r.document.content for r in similar_active if r.document.content]
        snippets.append(session_summary)

        consolidated = await self._consolidate(snippets, llm_func)

        triggered_ids = [r.document.id for r in similar_active]
        if triggered_ids:
            if self._soft_deprecation:
                deprecated_docs = [
                    VectorDocument(
                        id=r.document.id,
                        content=r.document.content,
                        vector=r.document.vector,
                        metadata={
                            **r.document.metadata,
                            "is_deprecated": True,
                            "superseded_by": doc_id,
                            "deprecated_at": now_iso,
                        },
                    )
                    for r in similar_active
                ]
                await self._vector.upsert(self._collection, deprecated_docs)
            else:
                await self._vector.delete(self._collection, triggered_ids)

        return RecurrenceResult(
            triggered=True,
            consolidated_content=consolidated,
            recurrence_count=recurrence_count,
            topic_summary=session_summary[:100],
        )

    async def _consolidate(
        self,
        snippets: list[str],
        llm_func: LLMFunc | None,
    ) -> str:
        """Consolidate multiple recurrent snippets into a single memory."""
        if llm_func is None:
            return snippets[-1]

        user_prompt = "Conversation snippets about the same topic:\n\n"
        for i, s in enumerate(snippets, 1):
            user_prompt += f"[Session {i}]: {s}\n"
        user_prompt += "\nConsolidate into a single long-term memory entry:"

        try:
            return await llm_func(_CONSOLIDATION_SYSTEM_PROMPT, user_prompt)
        except Exception as e:
            logger.warning("Recurrence consolidation LLM call failed: %s", e)
            return snippets[-1]

    async def _evict_old_entries(self) -> None:
        """Evict entries when buffer exceeds capacity to prevent unbounded growth."""
        count = await self._vector.count(self._collection)
        if count <= self._buffer_capacity:
            return

        excess = count - self._buffer_capacity
        docs, _ = await self._vector.scroll(self._collection, limit=self._buffer_capacity + excess)
        if not docs:
            return

        deprecated = [d.id for d in docs if d.metadata.get("is_deprecated")]
        if len(deprecated) >= excess:
            to_delete = deprecated[:excess]
        else:
            remaining_excess = excess - len(deprecated)
            non_deprecated = [d.id for d in docs if not d.metadata.get("is_deprecated")]
            to_delete = deprecated + non_deprecated[:remaining_excess]

        if to_delete:
            await self._vector.delete(self._collection, to_delete)


def _is_important(text: str) -> bool:
    """Check if text contains high-importance signals (health, safety, credentials)."""
    lower = text.lower()
    for kw in _IMPORTANCE_KEYWORDS_EN:
        if kw in lower:
            return True
    return any(kw in text for kw in _IMPORTANCE_KEYWORDS_CN)


def _is_trivial_summary(text: str) -> bool:
    """Check if text is trivial conversational chitchat with no long-term memory value.

    Filters out greetings, acknowledgments, and empty chitchat unless high importance signals
    are present.
    """
    cleaned = "".join(ch for ch in text.lower() if ch.isalnum() or ch.isspace()).strip()
    if not cleaned or cleaned in _TRIVIAL_SUMMARY_PATTERNS:
        return True
    return len(cleaned) <= 4 and not _is_important(text)

