"""A queue database's first open in a process requeues the sources a dead process left ``processing``."""

import sqlite3
import subprocess
import sys
import textwrap
import threading
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage

from myrm_agent_harness.toolkits.wiki.core.config import WikiCompileConfig, WikiConfig
from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure
from myrm_agent_harness.toolkits.wiki.pipeline import queue_recovery
from myrm_agent_harness.toolkits.wiki.pipeline.compiler import WikiCompiler
from myrm_agent_harness.toolkits.wiki.pipeline.queue import WikiIngestionQueue
from myrm_agent_harness.toolkits.wiki.pipeline.queue_recovery import requeue_orphaned_processing
from myrm_agent_harness.toolkits.wiki.retrieval.indexer import WikiIndexer

# A real process that claims one source the way the worker does, then dies without any cleanup.
_KILLED_MIDWAY = textwrap.dedent(
    """
    import asyncio
    import os
    import sys
    from pathlib import Path
    from unittest.mock import AsyncMock

    from myrm_agent_harness.toolkits.wiki.core.config import WikiConfig
    from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure
    from myrm_agent_harness.toolkits.wiki.pipeline.compiler import WikiCompiler

    compiler = WikiCompiler(AsyncMock(), WikiStructure(Path(sys.argv[1])), WikiConfig())
    asyncio.run(compiler.enqueue_changed_sources())
    compiler._queue.mark_processing(compiler._queue.get_pending_items(limit=1)[0]["id"])
    os._exit(137)
    """
)


@pytest.fixture
def wiki_structure(tmp_path: Path) -> WikiStructure:
    structure = WikiStructure(tmp_path)
    structure.ensure_structure()
    return structure


@pytest.fixture
def mock_llm() -> AsyncMock:
    llm = AsyncMock()
    llm.ainvoke.side_effect = [
        AIMessage(content='[{"name": "ML", "definition": "Machine Learning"}]'),
        AIMessage(content="## Compiled Truth\nML article."),
    ]
    return llm


@pytest.fixture
def mock_indexer() -> AsyncMock:
    indexer = AsyncMock(spec=WikiIndexer)
    indexer.upsert = AsyncMock()
    indexer.extract_and_upsert_edges = MagicMock()
    return indexer


def _kill_a_compile_midway(structure: WikiStructure) -> None:
    result = subprocess.run(
        [sys.executable, "-c", _KILLED_MIDWAY, str(structure.base_dir)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 137, result.stderr


def test_sources_a_killed_process_left_processing_are_requeued_by_the_next_one(wiki_structure: WikiStructure) -> None:
    for name in ("a.md", "b.md", "c.md"):
        (wiki_structure.raw_dir / name).write_text(f"content of {name}")
    _kill_a_compile_midway(wiki_structure)

    queue = WikiIngestionQueue(wiki_structure)

    assert queue.get_stats() == {"pending": 3, "processing": 0, "completed": 0, "failed": 0}


def test_a_second_queue_on_the_same_vault_leaves_the_live_workers_rows_alone(wiki_structure: WikiStructure) -> None:
    first = WikiIngestionQueue(wiki_structure)
    first.mark_processing(first.add_item("/tmp/a.md"))

    second = WikiIngestionQueue(wiki_structure)

    assert second.get_stats()["processing"] == 1


class _ParkingRegistry(dict[str, object]):
    """Holds every reader back until all threads have read, so a check-then-set lets each of them in."""

    def __init__(self, parties: int) -> None:
        super().__init__()
        self._all_have_read = threading.Barrier(parties, timeout=10)

    def _hold_back[T](self, value: T) -> T:
        self._all_have_read.wait()
        return value

    def __contains__(self, key: object) -> bool:
        return self._hold_back(super().__contains__(key))

    def __getitem__(self, key: str) -> object:
        return self._hold_back(super().__getitem__(key))

    def get(self, key: str, default: object = None, /) -> object:
        return self._hold_back(super().get(key, default))


def test_threads_opening_one_database_at_once_sweep_it_exactly_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    thread_count = 8
    monkeypatch.setattr(queue_recovery, "_OPENED_DATABASES", _ParkingRegistry(thread_count))
    sweeps: list[int] = []

    @contextmanager
    def counting_conn() -> Iterator[sqlite3.Connection]:
        sweeps.append(1)
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE ingestion_queue (status TEXT, updated_at TEXT)")
        yield conn
        conn.close()

    def open_database() -> None:
        requeue_orphaned_processing(tmp_path / "queue.db", counting_conn)

    threads = [threading.Thread(target=open_database) for _ in range(thread_count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(sweeps) == 1


@contextmanager
def _connection_to(database: Path) -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(database)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def test_a_sweep_that_failed_is_tried_again_by_the_next_open(tmp_path: Path) -> None:
    database = tmp_path / "queue.db"
    with _connection_to(database) as conn:
        conn.execute("CREATE TABLE ingestion_queue (status TEXT, updated_at TEXT)")
        conn.execute("INSERT INTO ingestion_queue (status) VALUES ('processing')")

    def locked() -> AbstractContextManager[sqlite3.Connection]:
        raise sqlite3.OperationalError("database is locked")

    with pytest.raises(sqlite3.OperationalError):
        requeue_orphaned_processing(database, locked)

    assert requeue_orphaned_processing(database, lambda: _connection_to(database)) == 1


@pytest.mark.asyncio
async def test_the_source_a_killed_compile_was_on_is_compiled_by_the_next_compile(
    wiki_structure: WikiStructure, mock_llm: AsyncMock, mock_indexer: AsyncMock
) -> None:
    (wiki_structure.raw_dir / "a.md").write_text("Machine learning is powerful.")
    _kill_a_compile_midway(wiki_structure)
    compile_config = WikiCompileConfig(require_approval=False, min_concept_mentions=1)
    compiler = WikiCompiler(mock_llm, wiki_structure, WikiConfig(), compile_config, indexer=mock_indexer)

    await compiler.compile_all()

    assert compiler._queue.get_stats() == {"pending": 0, "processing": 0, "completed": 1, "failed": 0}
