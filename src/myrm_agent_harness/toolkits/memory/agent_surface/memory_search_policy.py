"""Memory search policy and optional server-provided backends.

Framework-level ACL for ``memory_search_tool`` corpus routing. Server binds wiki
and conversation providers; runtime cannot broaden corpora beyond policy flags.

[INPUT]
- toolkits.memory.types (POS: Memory type system)

[OUTPUT]
- MemorySearchPolicy: Runtime ACL flags for wiki/sessions corpora and shared memory write bounds.
- MemorySearchBackends: Optional wiki/sessions providers plus wiki_structure for citation URI parity.
- resolve_search_corpora: Merge policy flags with requested corpus selection.

[POS]
Framework ACL gate for memory_search_tool corpus expansion beyond memory-only recall.
Located under ``toolkits/memory/agent_surface/``; root ``memory_search_policy.py`` is a stable import facade.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.memory.protocols.conversation_search import ConversationSearchProtocol
    from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure
    from myrm_agent_harness.toolkits.wiki.core.types import QueryResult

MemorySearchCorpus = Literal["memory", "wiki", "sessions", "all"]


@dataclass(frozen=True, slots=True)
class MemorySearchPolicy:
    """Runtime ACL for memory_search_tool corpus selection and memory write bounds."""

    allow_wiki: bool = False
    allow_sessions: bool = False
    allow_shared_write: bool = True


@dataclass(frozen=True, slots=True)
class MemorySearchBackends:
    """Optional backends bound by the application layer."""

    query_wiki: Callable[[str], Awaitable[QueryResult]] | None = None
    wiki_agent_id: str | None = None
    wiki_structure: WikiStructure | None = None
    conversation_provider: ConversationSearchProtocol | None = None


def resolve_search_corpora(
    corpus: MemorySearchCorpus,
    policy: MemorySearchPolicy,
) -> tuple[list[MemorySearchCorpus], str | None]:
    """Resolve requested corpus into concrete search targets with ACL enforcement."""
    if corpus == "memory":
        return (["memory"], None)
    if corpus == "wiki":
        if not policy.allow_wiki:
            return ([], "Wiki search is not enabled for this agent.")
        return (["wiki"], None)
    if corpus == "sessions":
        if not policy.allow_sessions:
            return (
                [],
                "Conversation history search is disabled. Enable it in Memory settings.",
            )
        return (["sessions"], None)
    if corpus == "all":
        corpora: list[MemorySearchCorpus] = ["memory"]
        if policy.allow_wiki:
            corpora.append("wiki")
        if policy.allow_sessions:
            corpora.append("sessions")
        return (corpora, None)
    return ([], f"Unknown corpus: {corpus}")
