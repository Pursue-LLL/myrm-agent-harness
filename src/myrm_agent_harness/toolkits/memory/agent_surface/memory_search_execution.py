"""Memory search execution helpers for memory_search_tool.

[INPUT]
- toolkits.memory.manager::MemoryManager (POS: Memory store orchestrator)
- toolkits.memory.conversation_search.types::ConversationSearchRequest (POS: Conversation search request DTO)

[OUTPUT]
- search_memory_corpus, search_wiki_corpus, search_sessions_corpus: Corpus-specific recall execution.

[POS]
Runtime execution layer for memory_search_tool corpus routing and formatting.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Awaitable
from datetime import datetime

from myrm_agent_harness.toolkits.memory.agent_surface.memory_citations import (
    cited_memory_ref,
    emit_cited_memory_ids,
)
from myrm_agent_harness.toolkits.memory.agent_surface.memory_recall_budget import (
    MAX_RECALL_OUTPUT_CHARS,
    budget_recall_line,
    line_cost,
    normalize_recall_limit,
)
from myrm_agent_harness.toolkits.memory.agent_surface.memory_recall_formatting import (
    RECALL_DRIFT_DEFENSE_FOOTER,
    finalize_recall_tool_output,
    format_recall_source_error_suffix,
    memory_age_label,
    recall_drift_defense_footer_chars,
    recall_preamble_overhead_chars,
)
from myrm_agent_harness.toolkits.memory.agent_surface.memory_recall_formatting import (
    channel_label as _channel_label,
)
from myrm_agent_harness.toolkits.memory.agent_surface.memory_recall_formatting import (
    is_stale as _is_stale,
)
from myrm_agent_harness.toolkits.memory.agent_surface.memory_recall_formatting import (
    parse_time_bound as _parse_time_bound,
)
from myrm_agent_harness.toolkits.memory.agent_surface.memory_search_policy import MemorySearchBackends
from myrm_agent_harness.toolkits.memory.conversation_search.format_output import (
    format_conversation_search_response,
)
from myrm_agent_harness.toolkits.memory.conversation_search.types import (
    MAX_CONVERSATION_SEARCH_LIMIT,
    ConversationSearchRequest,
)
from myrm_agent_harness.toolkits.memory.manager import MemoryManager
from myrm_agent_harness.toolkits.memory.types import (
    ClaimMemory,
    MemorySearchResult,
    MemoryType,
    SemanticMemory,
)

logger = logging.getLogger(__name__)


async def _run_with_timeout[T](
    coro: Awaitable[T],
    timeout_seconds: float | None,
    *,
    corpus: str,
) -> T | None:
    """Await a corpus backend under a wall-clock ceiling; None signals a timeout.

    Every memory_search_tool corpus path funnels through this helper so new
    corpora inherit the recall timeout guarantee without per-corpus boilerplate.
    """
    try:
        return await asyncio.wait_for(coro, timeout=timeout_seconds)
    except TimeoutError:
        logger.warning(
            "%s search timed out after %.1fs; failing open",
            corpus,
            timeout_seconds,
        )
        return None

_CODE_PATH_PATTERN = re.compile(
    r"(\/[a-zA-Z0-9_\-\.]+)+\/?|[a-zA-Z0-9_\-\.]+\.(py|ts|tsx|js|jsx|json|yaml|yml|md|rs|go|java|c|cpp|h|hpp)"
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
    max_body_chars = (
        MAX_RECALL_OUTPUT_CHARS
        - recall_drift_defense_footer_chars()
        - recall_preamble_overhead_chars()
    )
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
            await emit_cited_memory_ids(
                [],
                [],
                tool_name="memory_search_tool",
                retrieval_trace=manager.last_retrieval_trace,
            )
        return "No relevant memories found."

    for result in results:
        cat = next(
            (
                key
                for key, value in category_to_type.items()
                if value == result.memory_type
            ),
            result.memory_type.value,
        )
        memory = result.memory
        effective_time = max(memory.created_at, memory.updated_at)
        age = memory_age_label(effective_time)
        provenance = _channel_label(memory.scope.channel_id)
        prefix = (
            f"{provenance}[{cat}] (id: {memory.id}, score: {result.score:.2f}, {age}) "
        )
        suffix = ""
        if isinstance(memory, ClaimMemory):
            relation_type = (
                str(memory.metadata.get("latest_relationship_type", "")).strip().lower()
            )
            relation_suffix = f" relation={relation_type}" if relation_type else ""
            suffix += (
                f" [claim_graph freshness={memory.freshness} contradiction={memory.contradiction_status} "
                f"evidence={memory.evidence_count}{relation_suffix}]"
            )
        if isinstance(memory, SemanticMemory) and memory.source_error:
            suffix += format_recall_source_error_suffix(memory.source_error)
        if result.memory_type in (
            MemoryType.SEMANTIC,
            MemoryType.EPISODIC,
            MemoryType.CLAIM,
        ) and _is_stale(effective_time):
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
        cited_ids = [
            r.memory.id
            for r in displayed_results
            if r.memory.id and r.memory_type in ratable_types
        ]
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
        await emit_cited_memory_ids(
            [],
            [],
            tool_name="memory_search_tool",
            retrieval_trace=manager.last_retrieval_trace,
        )

    text = "\n".join(output)
    if output:
        text = finalize_recall_tool_output(text)
        text += RECALL_DRIFT_DEFENSE_FOOTER
    return text


async def search_wiki_corpus(
    backends: MemorySearchBackends,
    query: str,
    *,
    timeout_seconds: float | None = None,
) -> str:
    if backends.query_wiki is None:
        return "Wiki search is not available."
    from myrm_agent_harness.toolkits.memory.agent_surface.memory_citations import emit_sources
    from myrm_agent_harness.toolkits.wiki.retrieval.source_citations import (
        build_wiki_query_sources,
    )

    result = await _run_with_timeout(
        backends.query_wiki(query),
        timeout_seconds,
        corpus="Wiki",
    )
    if result is None:
        return "Wiki search timed out. Try a more specific query or retry."
    sources = build_wiki_query_sources(result, structure=backends.wiki_structure)
    if sources:
        indexed_sources: list[dict[str, object]] = []
        for index, source in enumerate(sources, start=1):
            entry = {**source, "index": index}
            if backends.wiki_agent_id:
                entry["agent_id"] = backends.wiki_agent_id
            indexed_sources.append(entry)
        await emit_sources(indexed_sources)
    body = (result.answer or "").strip() or "No relevant wiki content found."
    if body != "No relevant wiki content found.":
        from myrm_agent_harness.utils.context_format import (
            wrap_with_external_sources_tag,
        )

        body = wrap_with_external_sources_tag(body, source="LLM-Wiki")
    return body


async def search_sessions_corpus(
    backends: MemorySearchBackends,
    *,
    query: str,
    limit: int,
    since: datetime | None,
    until: datetime | None,
    expand_conversation_id: str | None = None,
    expand_message_id: str | None = None,
    expand_window: int = 5,
    timeout_seconds: float | None = None,
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
        expand_conversation_id=expand_conversation_id,
        expand_message_id=expand_message_id,
        expand_window=expand_window,
    )
    response = await _run_with_timeout(
        provider.search(request),
        timeout_seconds,
        corpus="Conversation",
    )
    if response is None:
        return "Conversation history search timed out. Try a more specific query or retry."
    return await format_conversation_search_response(response)
