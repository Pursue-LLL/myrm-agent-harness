"""memory_search_tool: unified read plane over memory / wiki / sessions.

[INPUT]
- toolkits.memory.manager::MemoryManager (POS: memory lifecycle manager)
- toolkits.memory.agent_surface.memory_search_policy (POS: corpus ACL and optional wiki/sessions backends)
- toolkits.memory.agent_surface.memory_search_execution (POS: memory/wiki/sessions search execution helpers)
- toolkits.memory.agent_surface.memory_recall_formatting / memory_recall_budget (POS: recall output SSOT)
- toolkits.memory.agent_surface.tool_result_sources (POS: pack/unpack metadata.sources for corpus results)

[OUTPUT]
- build_memory_search_tool: bind memory_search_tool to a manager, corpus policy and backends

[POS]
Read plane of the agent memory tools; write plane lives in save_tool / manage_tool.
"""

from __future__ import annotations

from typing import Literal

from langchain_core.tools import BaseTool, tool

from myrm_agent_harness.toolkits.memory.agent_surface.memory_agent_tools.common import (
    CATEGORY_TO_TYPE,
    parse_string_list,
)
from myrm_agent_harness.toolkits.memory.agent_surface.memory_recall_budget import (
    DEFAULT_RECALL_LIMIT,
    normalize_recall_limit,
)
from myrm_agent_harness.toolkits.memory.agent_surface.memory_recall_formatting import (
    format_profile_recall_output,
)
from myrm_agent_harness.toolkits.memory.agent_surface.memory_recall_formatting import (
    parse_time_bound as _parse_time_bound,
)
from myrm_agent_harness.toolkits.memory.agent_surface.memory_search_execution import (
    drill_down_single_memory,
    search_memory_corpus,
    search_sessions_corpus,
    search_wiki_corpus,
)
from myrm_agent_harness.toolkits.memory.agent_surface.memory_search_policy import (
    MemorySearchBackends,
    MemorySearchCorpus,
    MemorySearchPolicy,
    resolve_search_corpora,
)
from myrm_agent_harness.toolkits.memory.agent_surface.tool_result_sources import (
    pack_tool_result_with_sources,
    unpack_corpus_tool_result,
)
from myrm_agent_harness.toolkits.memory.manager import MemoryManager


def build_memory_search_tool(
    manager: MemoryManager,
    policy: MemorySearchPolicy,
    backends: MemorySearchBackends,
    *,
    description: str,
) -> BaseTool:
    """Create memory_search_tool bound to ``manager`` under the given corpus policy."""

    @tool("memory_search_tool", description=description)
    async def memory_search(
        query: str = "",
        corpus: MemorySearchCorpus = "memory",
        categories: list[str] | str | None = None,
        limit: int | str | None = DEFAULT_RECALL_LIMIT,
        profile_key: str | None = None,
        memory_id: str | None = None,
        detail_level: Literal["overview", "full"] = "overview",
        domain: Literal["user", "assistant", "task"] | None = None,
        since: str | None = None,
        until: str | None = None,
        expand_conversation_id: str | None = None,
        expand_message_id: str | None = None,
        expand_window: int = 5,
    ) -> str | dict[str, object]:
        """Search long-term memory.

        Optional partition filter:
          domain: 'user' for profiles/preferences, 'assistant' for identity/persona, 'task' for experiences/traps.
        """
        if memory_id:
            return await drill_down_single_memory(manager, memory_id, detail_level=detail_level)

        if profile_key:
            if corpus not in ("memory", "all"):
                return "profile_key lookup is only supported for corpus=memory."
            if not manager.has_relational:
                return "Profile memory is not enabled."
            value = await manager.get_profile_attribute(profile_key)
            if value is None:
                return f"No profile attribute '{profile_key}' found."
            return format_profile_recall_output(profile_key, value)

        corpora, reject_reason = resolve_search_corpora(corpus, policy)
        if reject_reason:
            return reject_reason
        if not corpora:
            return "No search corpora available."

        parsed_cats = parse_string_list(categories)
        category_names = [c for c in parsed_cats if c in CATEGORY_TO_TYPE] or None
        parsed_since = _parse_time_bound(since)
        parsed_until = _parse_time_bound(until)
        recall_limit = normalize_recall_limit(limit)
        sections: list[str] = []
        aggregated_sources: list[dict[str, object]] = []

        retrieval_timeout = getattr(getattr(manager, "_config", None), "retrieval", None)
        timeout_seconds = getattr(retrieval_timeout, "timeout_seconds", 5.0)

        for target in corpora:
            if target == "memory":
                memory_text = await search_memory_corpus(
                    manager,
                    query=query,
                    category_to_type=CATEGORY_TO_TYPE,
                    categories=category_names,
                    limit=recall_limit,
                    since=since,
                    until=until,
                    detail_level=detail_level,
                    domain=domain,
                )
                sections.append(f"## Memory\n{memory_text}")
            elif target == "wiki":
                wiki_result = await search_wiki_corpus(
                    backends,
                    query,
                    timeout_seconds=timeout_seconds,
                )
                wiki_text, wiki_sources = unpack_corpus_tool_result(wiki_result)
                aggregated_sources.extend(wiki_sources)
                sections.append(f"## Wiki\n{wiki_text}")
            elif target == "sessions":
                if expand_message_id and not expand_conversation_id:
                    return "expand_message_id requires expand_conversation_id when corpus=sessions."
                session_result = await search_sessions_corpus(
                    backends,
                    query=query,
                    limit=recall_limit,
                    since=parsed_since,
                    until=parsed_until,
                    expand_conversation_id=expand_conversation_id,
                    expand_message_id=expand_message_id,
                    expand_window=expand_window,
                    timeout_seconds=timeout_seconds,
                )
                session_text, session_sources = unpack_corpus_tool_result(session_result)
                aggregated_sources.extend(session_sources)
                sections.append(f"## Sessions\n{session_text}")

        if len(sections) == 1 and corpus != "all":
            single = sections[0]
            _prefix_map: dict[MemorySearchCorpus, str] = {
                "memory": "## Memory\n",
                "wiki": "## Wiki\n",
                "sessions": "## Sessions\n",
            }
            prefix = _prefix_map.get(corpus, "")
            if prefix and single.startswith(prefix):
                content = single[len(prefix) :]
            else:
                content = single
        else:
            content = "\n\n".join(sections)
        if aggregated_sources:
            return pack_tool_result_with_sources(content, aggregated_sources)
        return content

    return memory_search
