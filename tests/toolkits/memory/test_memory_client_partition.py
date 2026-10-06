# [POS] tests/toolkits/memory/test_memory_client_partition.py
# [INPUT] client_partition (types, workspace_resolver, guard), memory.config, memory._internal.scope
# [OUTPUT] test_client_scope_and_namespace_derivation, test_client_workspace_resolver_confinement, test_cross_client_leak_guard_screening, test_cross_client_write_validation

from pathlib import Path

import pytest

from myrm_agent_harness.toolkits.memory._internal.scope import build_scope, derive_namespaces
from myrm_agent_harness.toolkits.memory.client_partition import (
    ClientPartitionConfig,
    ClientWorkspaceResolver,
    CrossClientLeakGuard,
)
from myrm_agent_harness.toolkits.memory.config import (
    AgentMemoryPolicy,
    MemoryScopeLevel,
    MemoryWritePolicy,
)
from myrm_agent_harness.toolkits.memory.types import (
    MemoryScope,
    MemorySearchResult,
    MemoryType,
    SemanticMemory,
)


def test_client_scope_and_namespace_derivation() -> None:
    """Verify MemoryScopeLevel.CLIENT correctly integrates into namespace derivation."""
    policy = AgentMemoryPolicy(
        client_id="acme-corp",
        agent_id="researcher",
        read_scopes=(MemoryScopeLevel.GLOBAL, MemoryScopeLevel.CLIENT, MemoryScopeLevel.AGENT),
        write_policy=MemoryWritePolicy.CLIENT,
    )

    namespaces = derive_namespaces(
        namespaces=None,
        client_id="acme-corp",
        agent_id="researcher",
        channel_id=None,
        conversation_id=None,
        task_id=None,
        memory_policy=policy,
    )
    assert namespaces == ["global", "client:acme-corp", "agent:researcher"]

    scope = build_scope(
        namespaces=namespaces,
        client_id="acme-corp",
        agent_id="researcher",
        channel_id=None,
        conversation_id=None,
        task_id=None,
        memory_policy=policy,
    )
    assert scope.client_id == "acme-corp"
    assert scope.primary_namespace == "client:acme-corp"
    assert scope.namespaces == ["client:acme-corp"]


def test_client_workspace_resolver_confinement(tmp_path: Path) -> None:
    """Verify workspace resolver containment and path traversal protection."""
    resolver = ClientWorkspaceResolver(base_dir=tmp_path)

    # Valid resolution
    cfg = ClientPartitionConfig(client_id="client-alpha")
    desc = resolver.resolve_workspace(cfg, auto_create=True)
    assert desc.client_id == "client-alpha"
    assert desc.relative_path == "workspaces/clients/client-alpha"
    assert Path(desc.absolute_path).exists()
    assert Path(desc.absolute_path).is_relative_to(tmp_path)

    # Forbidden traversal attacks
    invalid_ids = ["../escaped", "../../etc/passwd", "client/nested", "client\\nested", "", "   "]
    for bad_id in invalid_ids:
        with pytest.raises(ValueError):
            resolver.validate_client_id(bad_id)


def test_cross_client_leak_guard_screening() -> None:
    """Verify screening drops foreign client memories and generates violation reports."""
    guard = CrossClientLeakGuard()

    # Memory A belongs to client-a
    mem_a = SemanticMemory(
        id="mem-1",
        content="Client A private Stripe API key and secrets",
        scope=MemoryScope(
            primary_namespace="client:client-a",
            namespaces=["client:client-a"],
            client_id="client-a",
        ),
    )
    res_a = MemorySearchResult(memory=mem_a, memory_type=MemoryType.SEMANTIC, score=0.95)

    # Memory B belongs to client-b
    mem_b = SemanticMemory(
        id="mem-2",
        content="Client B internal confidential salary grid",
        scope=MemoryScope(
            primary_namespace="client:client-b",
            namespaces=["client:client-b"],
            client_id="client-b",
        ),
    )
    res_b = MemorySearchResult(memory=mem_b, memory_type=MemoryType.SEMANTIC, score=0.92)

    # Global shared memory
    mem_global = SemanticMemory(
        id="mem-3",
        content="Python PEP8 coding standards",
        scope=MemoryScope(
            primary_namespace="global",
            namespaces=["global"],
            client_id=None,
        ),
    )
    res_global = MemorySearchResult(memory=mem_global, memory_type=MemoryType.SEMANTIC, score=0.88)

    candidates = [res_a, res_b, res_global]

    # When active client is client-a: mem_b MUST be purged, mem_a & mem_global allowed
    safe_a, report_a = guard.screen_search_results(candidates, active_client_id="client-a")
    assert len(safe_a) == 2
    assert [r.memory.id for r in safe_a] == ["mem-1", "mem-3"]
    assert report_a.total_evaluated == 3
    assert report_a.allowed_count == 2
    assert report_a.filtered_count == 1
    assert len(report_a.violations) == 1
    assert report_a.violations[0].offending_client_id == "client-b"

    # Strict isolation: disallow global read
    safe_strict, report_strict = guard.screen_search_results(
        candidates, active_client_id="client-a", allow_global=False
    )
    assert len(safe_strict) == 1
    assert safe_strict[0].memory.id == "mem-1"
    assert report_strict.filtered_count == 2


def test_cross_client_write_validation() -> None:
    """Verify cross-client memory write attempts are rejected with ValueError."""
    guard = CrossClientLeakGuard()

    valid_scope = MemoryScope(
        primary_namespace="client:client-x",
        namespaces=["client:client-x"],
        client_id="client-x",
    )
    guard.validate_write_scope(valid_scope, target_client_id="client-x")

    foreign_scope = MemoryScope(
        primary_namespace="client:client-y",
        namespaces=["client:client-y"],
        client_id="client-y",
    )
    with pytest.raises(ValueError, match="Cross-client memory write rejected"):
        guard.validate_write_scope(foreign_scope, target_client_id="client-x")
