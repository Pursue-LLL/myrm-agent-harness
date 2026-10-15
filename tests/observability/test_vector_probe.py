"""Doctor VectorDB probe against an embedded data directory that is really locked.

The directory lock is held by a second Qdrant client, which is what a second running copy of the
app does; nothing in the factory or the probe is mocked.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from myrm_agent_harness.observability.diagnostics.vector_probe import check_qdrant_health
from myrm_agent_harness.toolkits.vector.qdrant import create_embedded_store, embedded_fallback_paths
from myrm_agent_harness.toolkits.vector.qdrant.factory import evict_embedded_store


@pytest.mark.asyncio
async def test_probe_fails_while_another_client_holds_the_data_directory_lock(tmp_path: Path) -> None:
    qdrant_client = pytest.importorskip("qdrant_client")
    data_dir = tmp_path / "vector_store"
    holder = qdrant_client.QdrantClient(path=str(data_dir))
    store = await create_embedded_store(path=str(data_dir))
    try:
        assert not store.is_persistent
        assert str(data_dir.resolve()) in embedded_fallback_paths()

        report = await check_qdrant_health()

        assert report.status == "fail"
        assert report.component_name == "VectorDB"
        assert report.code == "ERR_VECTOR_STORE_ON_MEMORY_FALLBACK"
        assert "not being saved permanently" in report.message
    finally:
        await evict_embedded_store(str(data_dir))
        await store.hard_close()
        holder.close()

    assert str(data_dir.resolve()) not in embedded_fallback_paths()


@pytest.mark.asyncio
async def test_connection_failure_keeps_the_exception_in_detail_only(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("qdrant_client")
    failure = ConnectionError("refused by /secret/qdrant.sock")

    async def _raise(*_args: object, **_kwargs: object) -> None:
        raise failure

    monkeypatch.setattr("myrm_agent_harness.toolkits.vector.qdrant.create_vector_store", _raise)

    report = await check_qdrant_health()

    assert report.status == "fail"
    assert "connection failed" in report.message
    assert str(failure) in (report.detail or "")
    # The user-facing text names neither the backend nor the raw exception.
    for user_facing in (report.message, report.fix_suggestion or ""):
        assert str(failure) not in user_facing
        assert "qdrant" not in user_facing.lower()
