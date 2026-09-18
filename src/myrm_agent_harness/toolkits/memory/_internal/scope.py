"""Scope helpers for namespace derivation and channel-aware retrieval.


[INPUT]
- memory.config::{AgentMemoryPolicy, MemoryScopeLevel, MemoryWritePolicy} (POS: memory config and policy enums)
- memory.types::{AnyMemory, MemoryScope, MemorySearchResult} (POS: memory data models)

[OUTPUT]
- derive_namespaces: Namespace derivation from scope level
- bind_scope: MemoryScope binding to memory objects
- default_write_namespace: Durable write target so new memories stay recallable
- build_scope: MemoryScope construction from config
- apply_channel_affinity: Channel affinity reweighting for search results
- scope_for_write_target: Write target scope builder
- validate_namespace: Namespace validation helper

[POS]
Scope helper functions. Handles namespace derivation, MemoryScope binding, generic shared
namespace targeting, and channel affinity reweighting. Internal only — not part of the public API.
"""

from __future__ import annotations

import re
from typing import Literal

from myrm_agent_harness.toolkits.memory.config import AgentMemoryPolicy, MemoryScopeLevel, MemoryWritePolicy
from myrm_agent_harness.toolkits.memory.types import AnyMemory, MemoryScope, MemorySearchResult

_SCOPE_ORDER: tuple[MemoryScopeLevel, ...] = (
    MemoryScopeLevel.GLOBAL,
    MemoryScopeLevel.AGENT,
    MemoryScopeLevel.CHANNEL,
    MemoryScopeLevel.CONVERSATION,
    MemoryScopeLevel.TASK,
)

_AGENT_NAMESPACE_PREFIX = "agent:"

# Namespaces that only reach the session that created them once reads filter on
# ``primary_namespace``. Writes bound here are invisible to sibling sessions.
_SESSION_LOCAL_NAMESPACE_PREFIXES: tuple[str, ...] = ("conversation:", "task:")

MemoryWriteTarget = Literal["bound", "shared"]

_NAMESPACE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")


def validate_namespace(namespace: str) -> str:
    """Validate a framework namespace string and return it unchanged."""
    normalized = namespace.strip()
    if not normalized:
        raise ValueError("Memory namespace cannot be empty")
    if not _NAMESPACE_RE.fullmatch(normalized):
        raise ValueError(f"Invalid memory namespace: {namespace!r}")
    return normalized


def validate_namespaces(namespaces: list[str]) -> list[str]:
    """Validate and deduplicate namespaces while preserving order."""
    return list(dict.fromkeys(validate_namespace(namespace) for namespace in namespaces))


def _candidate_namespaces(
    *, agent_id: str | None, channel_id: str | None, conversation_id: str | None, task_id: str | None
) -> dict[MemoryScopeLevel, str]:
    candidates: dict[MemoryScopeLevel, str] = {
        MemoryScopeLevel.GLOBAL: "global",
        MemoryScopeLevel.AGENT: f"agent:{agent_id or 'default'}",
    }
    if channel_id:
        candidates[MemoryScopeLevel.CHANNEL] = f"channel:{channel_id}"
    if conversation_id:
        candidates[MemoryScopeLevel.CONVERSATION] = f"conversation:{conversation_id}"
    if task_id:
        candidates[MemoryScopeLevel.TASK] = f"task:{task_id}"
    return candidates


def _resolve_scope_identifiers(
    *,
    agent_id: str | None,
    channel_id: str | None,
    conversation_id: str | None,
    task_id: str | None,
    memory_policy: AgentMemoryPolicy | None,
) -> tuple[str | None, str | None, str | None, str | None]:
    if memory_policy is None:
        return agent_id, channel_id, conversation_id, task_id
    return (
        memory_policy.agent_id if memory_policy.agent_id is not None else agent_id,
        memory_policy.channel_id if memory_policy.channel_id is not None else channel_id,
        memory_policy.conversation_id if memory_policy.conversation_id is not None else conversation_id,
        memory_policy.task_id if memory_policy.task_id is not None else task_id,
    )


def derive_namespaces(
    *,
    namespaces: list[str] | None,
    agent_id: str | None,
    channel_id: str | None,
    conversation_id: str | None,
    task_id: str | None,
    memory_policy: AgentMemoryPolicy | None = None,
) -> list[str]:
    if namespaces:
        return validate_namespaces(namespaces)

    resolved_agent_id, resolved_channel_id, resolved_conversation_id, resolved_task_id = _resolve_scope_identifiers(
        agent_id=agent_id,
        channel_id=channel_id,
        conversation_id=conversation_id,
        task_id=task_id,
        memory_policy=memory_policy,
    )
    candidates = _candidate_namespaces(
        agent_id=resolved_agent_id,
        channel_id=resolved_channel_id,
        conversation_id=resolved_conversation_id,
        task_id=resolved_task_id,
    )
    read_scopes = memory_policy.read_scopes if memory_policy is not None else None
    levels = read_scopes or _SCOPE_ORDER
    return [candidates[level] for level in _SCOPE_ORDER if level in levels and level in candidates]


def build_scope(
    *,
    namespaces: list[str],
    agent_id: str | None,
    channel_id: str | None,
    conversation_id: str | None,
    task_id: str | None,
    memory_policy: AgentMemoryPolicy | None = None,
) -> MemoryScope:
    resolved_agent_id, resolved_channel_id, resolved_conversation_id, resolved_task_id = _resolve_scope_identifiers(
        agent_id=agent_id,
        channel_id=channel_id,
        conversation_id=conversation_id,
        task_id=task_id,
        memory_policy=memory_policy,
    )
    scope_namespaces = _bound_write_namespaces(list(namespaces))
    if memory_policy is not None and memory_policy.write_policy != MemoryWritePolicy.INHERIT:
        candidates = _candidate_namespaces(
            agent_id=resolved_agent_id,
            channel_id=resolved_channel_id,
            conversation_id=resolved_conversation_id,
            task_id=resolved_task_id,
        )
        target_level = MemoryScopeLevel(memory_policy.write_policy.value)
        target_namespace = candidates.get(target_level)
        if target_namespace is None:
            raise ValueError(f"Memory write policy '{memory_policy.write_policy.value}' requires a matching scope ID")
        scope_namespaces = [target_namespace]

    primary_namespace = resolve_primary_namespace(scope_namespaces)
    return MemoryScope(
        primary_namespace=primary_namespace,
        namespaces=scope_namespaces,
        agent_id=resolved_agent_id,
        channel_id=resolved_channel_id,
        conversation_id=resolved_conversation_id,
        task_id=resolved_task_id,
    )


def resolve_primary_namespace(namespaces: list[str]) -> str:
    """Pick the authoritative namespace a new memory is scoped to.

    Retrieval filters on ``primary_namespace ∈ manager.namespaces``, so a memory
    whose ``primary_namespace`` is session-local (``conversation:*`` / ``task:*``)
    can only ever be recalled by the session that created it: asking the same
    question in a fresh chat returns nothing. User-stated facts must therefore be
    scoped to the broadest durable namespace the reader can still reach, which is
    what makes them survive across sessions.

    Preference order: the ``agent:*`` scope, then ``global``, then the narrowest
    non-shared candidate. ``shared:*`` namespaces are excluded because they are a
    broadcast target rather than an ownership scope.
    """
    for namespace in namespaces:
        if namespace.startswith(_AGENT_NAMESPACE_PREFIX):
            return namespace
    for namespace in namespaces:
        if namespace == "global":
            return namespace
    return next(
        (namespace for namespace in reversed(namespaces) if not namespace.startswith("shared:")),
        namespaces[-1],
    )


def _bound_write_namespaces(namespaces: list[str]) -> list[str]:
    """Scope chain for a newly written memory.

    The chain itself is preserved (it documents the manager's visibility
    boundary and feeds the write-scope fence); only ``primary_namespace`` — the
    single value retrieval actually filters on — is narrowed to a durable scope.
    """
    return list(namespaces)


def bind_scope(memory: AnyMemory, scope: MemoryScope) -> AnyMemory:
    if memory.scope.namespaces:
        return memory
    memory.scope = scope.model_copy(deep=True)
    return memory


def scope_for_write_target(
    base_scope: MemoryScope, namespaces: list[str], write_target: MemoryWriteTarget
) -> MemoryScope:
    scope = base_scope.model_copy(deep=True)
    if write_target == "shared" and namespaces:
        target_namespace = next(
            (namespace for namespace in reversed(namespaces) if namespace.startswith("shared:")),
            namespaces[0],
        )
        scope.primary_namespace = target_namespace
        scope.namespaces = [target_namespace]
    return scope


def apply_channel_affinity(
    results: list[MemorySearchResult], *, current_channel_id: str | None
) -> list[MemorySearchResult]:
    if not current_channel_id:
        return results

    adjusted: list[MemorySearchResult] = []
    for result in results:
        memory_channel = result.memory.scope.channel_id
        if not memory_channel:
            adjusted.append(result)
            continue

        score = result.score * 1.15 if memory_channel == current_channel_id else result.score * 0.92
        adjusted.append(result.model_copy(update={"score": min(score, 1.0)}))
    return adjusted
