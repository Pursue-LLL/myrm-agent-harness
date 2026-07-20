"""Memory search execution helpers for memory_search_tool."""

from __future__ import annotations

import logging
import re
from datetime import datetime

from myrm_agent_harness.toolkits.memory.conversation_search.format_output import format_conversation_search_response
from myrm_agent_harness.toolkits.memory.conversation_search.types import (
    DEFAULT_CONVERSATION_SEARCH_LIMIT,
    MAX_CONVERSATION_SEARCH_LIMIT,
    ConversationSearchRequest,
)
from myrm_agent_harness.toolkits.memory.manager import MemoryManager
from myrm_agent_harness.toolkits.memory.memory_citations import cited_memory_ref, emit_cited_memory_ids
from myrm_agent_harness.toolkits.memory.memory_recall_budget import (
    MAX_RECALL_OUTPUT_CHARS,
    budget_recall_line,
    line_cost,
    normalize_recall_limit,
)
from myrm_agent_harness.toolkits.memory.memory_recall_formatting import (
    channel_label as _channel_label,
)
from myrm_agent_harness.toolkits.memory.memory_recall_formatting import (
    is_stale as _is_stale,
)
from myrm_agent_harness.toolkits.memory.memory_recall_formatting import (
    memory_age_label,
)
from myrm_agent_harness.toolkits.memory.memory_recall_formatting import (
    parse_time_bound as _parse_time_bound,
)
from myrm_agent_harness.toolkits.memory.memory_search_policy import MemorySearchBackends
from myrm_agent_harness.toolkits.memory.types import (
    ClaimMemory,
    MemorySearchResult,
    MemoryType,
    SemanticMemory,
)

logger = logging.getLogger(__name__)

_CODE_PATH_PATTERN = re.compile(
    r"(\/[a-zA-Z0-9_\-\.]+)+\/?|[a-zA-Z0-9_\-\.]+\.(py|ts|tsx|js|jsx|json|yaml|yml|md|rs|go|java|c|cpp|h|hpp)"
)

_DRIFT_DEFENSE_FOOTER = (
    "\n---\n"
    "Note: Before acting on recalled memories:\n"
    "- If a memory references files/functions → verify they still exist\n"
    "- If a memory states configs/versions → check current project state\n"
    "- If a memory conflicts with current observations → trust current observation\n"
    "To fix outdated memories: use memory_manage(action='correct') or memory_manage(action='delete')"
)


async def search_memory_corpus(
    manager: MemoryManager,
    *,
    query: str,
    category_to_type: dict[str, MemoryType],
    categories: list[str] | None,
    limit: int | str | None,
    since: str | None,
    until: str | None,
) -> str:
    """Search long-term memory corpus (includes active session buffer)."""
    parsed_since = _parse_time_bound(since)
    parsed_until = _parse_time_bound(until)
    recall_limit = normalize_recall_limit(limit)
    types: list[MemoryType] | None = None
    if categories:
        valid = [category_to_type[c] for c in categories if c in category_to_type]
        types = valid or None

    results = await manager.search(
        query,
        memory_types=types,
        limit=recall_limit,
        since=parsed_since,
        until=parsed_until,
    )
    output: list[str] = []
    displayed_results: list[MemorySearchResult] = []
    max_body_chars = MAX_RECALL_OUTPUT_CHARS - (len(_DRIFT_DEFENSE_FOOTER) if results else 0)
    output_chars = 0
    truncated_by_budget = False

    session = manager.active_session
    if session and session.buffer_size > 0 and query:
        for buffered in session.search_buffer(query):
            budgeted = budget_recall_line(
                prefix="[buffered] ",
                content=buffered.content,
                suffix="",
                output_chars=output_chars,
                max_body_chars=max_body_chars,
            )
            if budgeted.line is None:
                truncated_by_budget = True
                break
            output.append(budgeted.line)
            output_chars = budgeted.next_chars
            truncated_by_budget = truncated_by_budget or budgeted.truncated

    if not results and not output:
        if manager.last_retrieval_trace is not None:
            await emit_cited_memory_ids([], [], tool_name="memory_search_tool", retrieval_trace=manager.last_retrieval_trace)
        return "No relevant memories found."

    for result in results:
        cat = next(
            (key for key, value in category_to_type.items() if value == result.memory_type),
            result.memory_type.value,
        )
        memory = result.memory
        age = memory_age_label(memory.created_at)
        provenance = _channel_label(memory.scope.channel_id)
        prefix = f"{provenance}[{cat}] (id: {memory.id}, score: {result.score:.2f}, {age}) "
        suffix = ""
        if isinstance(memory, ClaimMemory):
            relation_type = str(memory.metadata.get("latest_relationship_type", "")).strip().lower()
            relation_suffix = f" relation={relation_type}" if relation_type else ""
            suffix += (
                f" [claim_graph freshness={memory.freshness} contradiction={memory.contradiction_status} "
                f"evidence={memory.evidence_count}{relation_suffix}]"
            )
        if isinstance(memory, SemanticMemory) and memory.source_error:
            suffix += f" (avoid: {memory.source_error})"
        if result.memory_type in (MemoryType.SEMANTIC, MemoryType.EPISODIC, MemoryType.CLAIM) and _is_stale(
            memory.created_at
        ):
            if _CODE_PATH_PATTERN.search(memory.content):
                suffix += (
                    "\n[CRITICAL: Outdated memory referencing potential paths. "
                    "YOU MUST USE Read/Grep TOOLS TO VERIFY BEFORE CITING IF AVAILABLE, OR DO NOT BLINDLY TRUST]"
                )
            else:
                suffix += " (may be outdated — verify before citing)"
        budgeted = budget_recall_line(
            prefix=prefix,
            content=result.content,
            suffix=suffix,
            output_chars=output_chars,
            max_body_chars=max_body_chars,
        )
        if budgeted.line is None:
            truncated_by_budget = True
            break
        output.append(budgeted.line)
        displayed_results.append(result)
        output_chars = budgeted.next_chars
        truncated_by_budget = truncated_by_budget or budgeted.truncated

    if truncated_by_budget:
        notice = (
            "[recall_budget] Some recalled content was truncated to keep this tool result within "
            f"{MAX_RECALL_OUTPUT_CHARS} chars. Refine the query or lower limit for more detail."
        )
        if output_chars + line_cost(notice) <= max_body_chars:
            output.append(notice)

    if displayed_results:
        ratable_types = (MemoryType.SEMANTIC, MemoryType.EPISODIC)
        cited_ids = [r.memory.id for r in displayed_results if r.memory.id and r.memory_type in ratable_types]
        cited_refs = [
            cited_memory_ref(r.memory, r.memory_type, r.score)
            for r in displayed_results
            if r.memory.id and r.memory_type in ratable_types
        ]
        if cited_ids:
            manager.set_last_cited_memory_ids(cited_ids)
        if cited_ids or manager.last_retrieval_trace is not None:
            await emit_cited_memory_ids(
                cited_ids,
                cited_refs,
                tool_name="memory_search_tool",
                retrieval_trace=manager.last_retrieval_trace,
            )
    elif manager.last_retrieval_trace is not None:
        await emit_cited_memory_ids([], [], tool_name="memory_search_tool", retrieval_trace=manager.last_retrieval_trace)

    text = "\n".join(output)
    if displayed_results:
        text += _DRIFT_DEFENSE_FOOTER
    return text


async def search_wiki_corpus(
    backends: MemorySearchBackends,
    query: str,
) -> str:
    if backends.query_wiki is None:
        return "Wiki search is not available."
    wiki_answer = await backends.query_wiki(query)
    body = wiki_answer.strip() or "No relevant wiki content found."
    return body


async def search_sessions_corpus(
    backends: MemorySearchBackends,
    *,
    query: str,
    limit: int,
    since: datetime | None,
    until: datetime | None,
) -> str:
    provider = backends.conversation_provider
    if provider is None:
        return "Conversation history search is not available."

    query_text = query.strip()
    requested_mode = "recent" if query_text in ("", "*") else None
    request = ConversationSearchRequest(
        query="" if query_text == "*" else query_text,
        mode=requested_mode,
        scope="current_agent",
        lineage="all",
        limit=min(max(limit, 1), MAX_CONVERSATION_SEARCH_LIMIT),
        min_score=0.2,
        since=since,
        until=until,
    )
    response = await provider.search(request)
    return await format_conversation_search_response(response)
