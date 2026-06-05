"""Pre-compaction semantic memory recall service.

[INPUT]
- memory.manager::MemoryManager (POS: unified memory facade)
- memory.memory_recall_budget::* (POS: recall output budget guardrails)

[OUTPUT]
- MemoryPreCompactService: default ContextPreCompactCallback implementation

[POS]
Framework-default pre-compaction recall. Searches durable memory and formats a bounded
HumanMessage injection without coupling to server business logic.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from myrm_agent_harness.agent.context_management.infra.schemas import PreCompactInjection
from myrm_agent_harness.core.security.detection.content_boundary import sanitize, wrap_untrusted
from myrm_agent_harness.toolkits.memory.manager import MemoryManager
from myrm_agent_harness.toolkits.memory.memory_recall_budget import (
    budget_recall_line,
    line_cost,
    normalize_recall_limit,
)
from myrm_agent_harness.toolkits.memory.memory_recall_formatting import memory_age_label
from myrm_agent_harness.toolkits.memory.types import MemorySearchResult

logger = logging.getLogger(__name__)

DEFAULT_BUDGET_TOKENS = 1500
DEFAULT_TIMEOUT_SECONDS = 3.0
_CHARS_PER_TOKEN = 4
_MEMORY_ID_IN_MESSAGE_RE = re.compile(r"\bid:([a-zA-Z0-9_-]{8,})\b")
_PRE_COMPACT_RECALL_MARKER = "<pre_compact_recall_context"


@dataclass(frozen=True, slots=True)
class MemoryPreCompactConfig:
    enabled: bool = True
    budget_tokens: int = DEFAULT_BUDGET_TOKENS
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    search_limit: int = 8


class MemoryPreCompactService:
    """Recall durable memories before context compaction mutates the message list."""

    def __init__(self, manager: MemoryManager, config: MemoryPreCompactConfig | None = None) -> None:
        self._manager = manager
        self._config = config or MemoryPreCompactConfig()

    async def build_injection(
        self,
        *,
        messages: list[BaseMessage],
        chat_id: str | None,
        user_id: str | None,
        compaction_tier: str,
        token_pressure_ratio: float,
        user_goal_hint: str,
    ) -> PreCompactInjection | None:
        if not self._config.enabled:
            return None

        query = _build_query(messages, user_goal_hint)
        if not query:
            return None

        budget_tokens = _dynamic_budget(self._config.budget_tokens, token_pressure_ratio)
        excluded_ids = _collect_memory_ids(messages)

        try:
            results = await asyncio.wait_for(
                self._manager.search(
                    query,
                    limit=normalize_recall_limit(self._config.search_limit),
                    use_rrf=True,
                ),
                timeout=self._config.timeout_seconds,
            )
        except TimeoutError:
            logger.warning("[PreCompact] memory search timed out after %.1fs", self._config.timeout_seconds)
            return None
        except Exception as exc:
            logger.warning("[PreCompact] memory search failed: %s", exc)
            return None

        filtered = [item for item in results if item.id not in excluded_ids]
        archive_body, archive_ids, archive_tokens = await _fetch_archive_checkpoint_milestone(
            self._manager,
            chat_id=chat_id,
            excluded_ids=excluded_ids,
            budget_tokens=max(400, budget_tokens // 3),
        )

        if not filtered and not archive_body:
            return None

        body, recalled_ids, used_tokens = _format_recall_body(filtered, budget_tokens)
        if archive_body:
            if body:
                body = f"{archive_body}\n\n{body}"
            else:
                body = archive_body
            recalled_ids = archive_ids + recalled_ids
            used_tokens += archive_tokens

        if not body or not recalled_ids:
            return None

        wrapped = wrap_untrusted(body, source="pre_compact_recall")
        content = (
            f'{_PRE_COMPACT_RECALL_MARKER} tier="{compaction_tier}" chat="{chat_id or "unknown"}">\n'
            f"{wrapped}\n"
            f"</pre_compact_recall_context>"
        )
        message = HumanMessage(content=content)
        return PreCompactInjection(
            message=message,
            recalled_ids=tuple(recalled_ids),
            token_estimate=used_tokens,
            query=query,
            compaction_tier=compaction_tier,
        )


def _dynamic_budget(base_budget: int, token_pressure_ratio: float) -> int:
    clamped_ratio = min(max(token_pressure_ratio, 0.0), 1.0)
    scaled = int(base_budget * (0.55 + 0.45 * clamped_ratio))
    return max(800, min(scaled, 2000))


def _build_query(messages: list[BaseMessage], user_goal_hint: str) -> str:
    parts: list[str] = []
    if user_goal_hint.strip():
        parts.append(user_goal_hint.strip())

    recent_turns: list[str] = []
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            text = _message_text(message)
            if text and _PRE_COMPACT_RECALL_MARKER not in text:
                recent_turns.append(text)
        elif isinstance(message, AIMessage):
            text = _message_text(message)
            if text:
                recent_turns.append(text[:400])
        if len(recent_turns) >= 5:
            break

    for text in reversed(recent_turns):
        parts.append(text)

    query = "\n".join(part for part in parts if part).strip()
    return query[:4000]


def _message_text(message: BaseMessage) -> str:
    content = message.content
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        chunks: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                text = block.get("text")
                if isinstance(text, str):
                    chunks.append(text)
        return "\n".join(chunks).strip()
    return ""


def _collect_memory_ids(messages: list[BaseMessage]) -> set[str]:
    ids: set[str] = set()
    for message in messages[:30]:
        text = _message_text(message)
        if not text:
            continue
        ids.update(_MEMORY_ID_IN_MESSAGE_RE.findall(text))
    return ids


def _format_recall_body(
    results: list[MemorySearchResult],
    budget_tokens: int,
) -> tuple[str, list[str], int]:
    max_chars = budget_tokens * _CHARS_PER_TOKEN
    lines: list[str] = []
    recalled_ids: list[str] = []
    output_chars = 0

    for result in results:
        memory = result.memory
        age = memory_age_label(memory.created_at)
        prefix = f"- [{result.memory_type.value}] id:{memory.id} score:{result.score:.2f} age:{age} "
        suffix = ""
        budgeted = budget_recall_line(
            prefix=prefix,
            content=sanitize(memory.content),
            suffix=suffix,
            output_chars=output_chars,
            max_body_chars=max_chars,
        )
        if budgeted.line is None:
            break
        lines.append(budgeted.line)
        recalled_ids.append(memory.id)
        output_chars += line_cost(budgeted.line)

    if not lines:
        return "", [], 0

    body = "## Pre-Compaction Memory Recall\n" + "\n".join(lines)
    used_tokens = max(1, len(body) // _CHARS_PER_TOKEN)
    return body, recalled_ids, used_tokens


async def _fetch_archive_checkpoint_milestone(
    manager: MemoryManager,
    *,
    chat_id: str | None,
    excluded_ids: set[str],
    budget_tokens: int,
) -> tuple[str, list[str], int]:
    if budget_tokens <= 0 or not chat_id:
        return "", [], 0

    try:
        from myrm_agent_harness.agent.context_management.archive_checkpoint.store import (
            list_recent_checkpoints,
        )

        records = await asyncio.wait_for(
            list_recent_checkpoints(manager, chat_id=chat_id, limit=8),
            timeout=2.0,
        )
    except Exception as exc:
        logger.debug("[PreCompact] archive checkpoint scroll failed: %s", exc)
        return "", [], 0

    records = [record for record in records if record.memory_id not in excluded_ids]
    if not records:
        return "", [], 0

    max_chars = budget_tokens * _CHARS_PER_TOKEN
    lines: list[str] = []
    recalled_ids: list[str] = []
    output_chars = 0

    for record in records[:4]:
        prefix = f"- [archive_checkpoint] id:{record.memory_id} tool:{record.tool_name} path:{record.archive_path} "
        budgeted = budget_recall_line(
            prefix=prefix,
            content=sanitize(record.summary),
            suffix="",
            output_chars=output_chars,
            max_body_chars=max_chars,
        )
        if budgeted.line is None:
            break
        lines.append(budgeted.line)
        recalled_ids.append(record.memory_id)
        output_chars += line_cost(budgeted.line)

    if not lines:
        return "", [], 0

    body = "## Recent Archive Checkpoints\n" + "\n".join(lines)
    used_tokens = max(1, len(body) // _CHARS_PER_TOKEN)
    return body, recalled_ids, used_tokens
