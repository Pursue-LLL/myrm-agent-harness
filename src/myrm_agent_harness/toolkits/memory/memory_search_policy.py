"""Memory search policy and optional server-provided backends.

Framework-level ACL for ``memory_search_tool`` corpus routing. Server binds wiki
and conversation providers; runtime cannot broaden corpora beyond policy flags.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal, TYPE_CHECKING

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.memory.protocols.conversation_search import ConversationSearchProtocol

MemorySearchCorpus = Literal["memory", "wiki", "sessions", "all"]


@dataclass(frozen=True, slots=True)
class MemorySearchPolicy:
    """Runtime ACL for memory_search_tool corpus selection."""

    allow_wiki: bool = False
    allow_sessions: bool = False


@dataclass(frozen=True, slots=True)
class MemorySearchBackends:
    """Optional backends bound by the application layer."""

    query_wiki: Callable[[str], Awaitable[str]] | None = None
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
