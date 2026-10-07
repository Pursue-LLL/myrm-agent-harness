# ============================================================================
# Unit Tests: Workspace File Watch Context Invalidation Gateway (Item 165)
# ============================================================================

import pytest

from myrm_agent_harness.agent.context_management.file_watch import (
    DocumentFreshnessStatus,
    FileMutationKind,
    WorkspaceFileWatchContextGateway,
)


def test_bind_session_document_and_query() -> None:
    """Test binding session document and verifying fingerprint and fresh state."""
    gateway = WorkspaceFileWatchContextGateway()
    session_id = "sess-doc-1"
    file_path = "docs/architecture.md"
    content = "# Myrm Architecture\nVersion 1.0"

    binding = gateway.bind_session_document(session_id, file_path, content, mtime_ns=1000)

    assert binding.session_id == session_id
    assert binding.path == "docs/architecture.md"
    assert binding.status == DocumentFreshnessStatus.FRESH
    assert len(binding.fingerprint.sha256) == 64
    assert binding.fingerprint.byte_size == len(content.encode("utf-8"))

    # Query binding
    queried = gateway.get_session_binding(session_id, file_path)
    assert queried is not None
    assert queried.fingerprint.sha256 == binding.fingerprint.sha256
    assert queried.cached_content == content


def test_notify_workspace_mutation_stale_invalidation_and_nudge() -> None:
    """Test external modification invalidating bound session cache and generating ambient nudges."""
    gateway = WorkspaceFileWatchContextGateway()
    s1 = "session-alpha"
    s2 = "session-beta"
    file_path = "src/config.json"
    initial_content = '{"env": "development"}'

    gateway.bind_session_document(s1, file_path, initial_content)
    gateway.bind_session_document(s2, file_path, initial_content)

    # Identical mutation should be ignored (no-op write)
    nudges_noop = gateway.notify_workspace_mutation(
        path=file_path,
        mutation_kind=FileMutationKind.MODIFIED,
        new_content=initial_content,
    )
    assert len(nudges_noop) == 0
    assert gateway.get_session_binding(s1, file_path).status == DocumentFreshnessStatus.FRESH

    # Substantial modification
    updated_content = '{"env": "production", "debug": false}'
    nudges = gateway.notify_workspace_mutation(
        path=file_path,
        mutation_kind=FileMutationKind.MODIFIED,
        new_content=updated_content,
    )
    assert len(nudges) == 2
    assert {n.session_id for n in nudges} == {s1, s2}

    # Verify both sessions marked stale
    b1 = gateway.get_session_binding(s1, file_path)
    b2 = gateway.get_session_binding(s2, file_path)
    assert b1.status == DocumentFreshnessStatus.STALE
    assert b2.status == DocumentFreshnessStatus.STALE

    # Consume pending nudges
    consumed_s1 = gateway.consume_pending_nudges(s1)
    assert len(consumed_s1) == 1
    assert "src/config.json" in consumed_s1[0].nudge_message or "config.json" in consumed_s1[0].nudge_message

    # Repeated consume returns empty
    assert len(gateway.consume_pending_nudges(s1)) == 0


def test_auto_ingress_stale_documents() -> None:
    """Test auto-ingress incremental reload for stale document bindings."""
    gateway = WorkspaceFileWatchContextGateway()
    session_id = "session-reindex"
    path = "reports/summary.csv"
    initial_data = "col1,col2\n1,2"
    gateway.bind_session_document(session_id, path, initial_data)

    new_data = "col1,col2,col3\n1,2,3\n4,5,6"
    gateway.notify_workspace_mutation(
        path=path,
        mutation_kind=FileMutationKind.MODIFIED,
        new_content=new_data,
    )
    assert gateway.get_session_binding(session_id, path).status == DocumentFreshnessStatus.STALE

    # Mock external disk file reader
    disk_store = {path: new_data}

    def mock_reader(p: str) -> str:
        return disk_store[p]

    results = gateway.auto_ingress_stale_documents(session_id, mock_reader)
    assert len(results) == 1
    res = results[0]
    assert res.path == path
    assert res.status == DocumentFreshnessStatus.RE_INDEXED
    assert res.byte_delta == len(new_data.encode("utf-8")) - len(initial_data.encode("utf-8"))

    # Bound cache should now hold the new content and status RE_INDEXED
    refreshed_binding = gateway.get_session_binding(session_id, path)
    assert refreshed_binding.status == DocumentFreshnessStatus.RE_INDEXED
    assert refreshed_binding.cached_content == new_data


def test_deleted_file_eviction_and_unbound_isolation() -> None:
    """Test file deletion marking binding as EVICTED and manual eviction cleanup."""
    gateway = WorkspaceFileWatchContextGateway()
    session_id = "session-del"
    path = "temp/notes.txt"
    gateway.bind_session_document(session_id, path, "meeting notes")

    # Unbound file mutation should have zero impact
    unbound_nudges = gateway.notify_workspace_mutation(
        path="other/unrelated.txt",
        mutation_kind=FileMutationKind.MODIFIED,
        new_content="something",
    )
    assert len(unbound_nudges) == 0

    # Delete bound file
    del_nudges = gateway.notify_workspace_mutation(
        path=path,
        mutation_kind=FileMutationKind.DELETED,
    )
    assert len(del_nudges) == 1
    assert gateway.get_session_binding(session_id, path).status == DocumentFreshnessStatus.EVICTED

    # Explicit eviction
    assert gateway.evict_session_binding(session_id, path) is True
    assert gateway.get_session_binding(session_id, path) is None
    # Repeated evict returns False
    assert gateway.evict_session_binding(session_id, path) is False
