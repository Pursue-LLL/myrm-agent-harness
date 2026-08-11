from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage

from myrm_agent_harness.toolkits.wiki.core.config import WikiCompileConfig
from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure
from myrm_agent_harness.toolkits.wiki.core.types import ConceptInfo
from myrm_agent_harness.toolkits.wiki.pipeline.sidecar import (
    WikiDirectorySidecarBuilder,
    build_directory_sidecars,
)


class _FakeIndexer:
    def __init__(self) -> None:
        self.upserts: list[tuple[str, int, str]] = []
        self.deletes: list[tuple[str, int]] = []
        self.delete_all_calls = 0

    async def upsert_sidecar(self, dir_path: str, *, level: int, content: str) -> None:
        self.upserts.append((dir_path, level, content))

    async def delete_sidecar(self, dir_path: str, *, level: int) -> None:
        self.deletes.append((dir_path, level))

    async def delete_all_sidecars(self) -> None:
        self.delete_all_calls += 1


@pytest.mark.asyncio
async def test_sidecar_builder_incremental_skip(tmp_path):
    structure = WikiStructure(tmp_path)
    structure.ensure_structure()
    concept_file = structure.get_concept_file_path("Ops/Runbook")
    concept_file.write_text("## Compiled Truth\nRunbook steps and rollback plan.", encoding="utf-8")

    llm = AsyncMock()
    llm.ainvoke.return_value = AIMessage(
        content='{"abstract":"Ops summary","overview":"Ops detailed overview"}'
    )
    indexer = _FakeIndexer()
    concept = ConceptInfo(
        name="Ops/Runbook",
        definition="Runbook",
        source_files=["ops.md"],
        related_concepts=[],
    )

    first = await build_directory_sidecars(
        llm,
        structure,
        WikiCompileConfig(),
        touched_concepts=[concept],
        indexer=indexer,
    )
    assert first.rebuilt_directories >= 1
    assert llm.ainvoke.await_count >= 1

    abstract_path, overview_path = structure.get_directory_sidecar_paths("ops", create=False)
    assert abstract_path.exists()
    assert overview_path.exists()
    assert "summary" in abstract_path.read_text(encoding="utf-8").lower()

    before_count = llm.ainvoke.await_count
    second = await build_directory_sidecars(
        llm,
        structure,
        WikiCompileConfig(),
        touched_concepts=[],
        indexer=indexer,
    )
    assert second.skipped_directories >= 1
    assert llm.ainvoke.await_count == before_count


@pytest.mark.asyncio
async def test_sidecar_builder_clears_sidecars_when_no_concepts(tmp_path):
    structure = WikiStructure(tmp_path)
    structure.ensure_structure()
    concept_file = structure.get_concept_file_path("Domain/Topic")
    concept_file.write_text("## Compiled Truth\nKnowledge.", encoding="utf-8")

    llm = AsyncMock()
    llm.ainvoke.return_value = AIMessage(
        content='{"abstract":"Domain summary","overview":"Domain overview"}'
    )
    indexer = _FakeIndexer()
    concept = ConceptInfo(
        name="Domain/Topic",
        definition="Topic",
        source_files=["domain.md"],
        related_concepts=[],
    )
    await build_directory_sidecars(
        llm,
        structure,
        WikiCompileConfig(),
        touched_concepts=[concept],
        indexer=indexer,
    )
    concept_file.unlink()

    result = await build_directory_sidecars(
        llm,
        structure,
        WikiCompileConfig(),
        touched_concepts=[],
        indexer=indexer,
    )
    assert result.removed_directories >= 1
    assert indexer.delete_all_calls == 1


@pytest.mark.asyncio
async def test_sidecar_builder_reasoning_model_content_empty(tmp_path):
    """Reasoning 模型 content 为空时回退到 additional_kwargs["reasoning_content"]。"""
    structure = WikiStructure(tmp_path)
    structure.ensure_structure()
    concept_file = structure.get_concept_file_path("Ops/Runbook")
    concept_file.write_text("## Compiled Truth\nRunbook steps and rollback plan.", encoding="utf-8")

    llm = AsyncMock()
    llm.ainvoke.return_value = AIMessage(
        content="",
        additional_kwargs={"reasoning_content": '{"abstract":"Ops summary","overview":"Ops detailed overview"}'},
    )
    indexer = _FakeIndexer()
    concept = ConceptInfo(
        name="Ops/Runbook",
        definition="Runbook",
        source_files=["ops.md"],
        related_concepts=[],
    )

    result = await build_directory_sidecars(
        llm,
        structure,
        WikiCompileConfig(),
        touched_concepts=[concept],
        indexer=indexer,
    )
    assert result.rebuilt_directories >= 1
    abstract_path, _overview_path = structure.get_directory_sidecar_paths("ops", create=False)
    assert "summary" in abstract_path.read_text(encoding="utf-8").lower()


def test_parse_sidecar_payload_dirty_llm_outputs() -> None:
    """Robust parser tolerates the dirty formats reasoning/weak models emit.

    The previous greedy-regex + strict json.loads path dropped the directory
    summary for all four cases below, degrading to the raw-concatenation
    fallback.
    """
    cases = [
        (
            'Format like {"abstract": "x", "overview": "y"}. '
            'Now real: {"abstract": "A", "overview": "O"}',
            ("A", "O"),
        ),
        ('{"abstract": "A", "overview": "O",}', ("A", "O")),
        ('{"abstract": "line1\nline2", "overview": "O"}', ("line1\nline2", "O")),
        ('{"abstract": "wrong", "overview": "wrong"}\n{"abstract": "A", "overview": "O"}', ("A", "O")),
    ]
    for raw, expected in cases:
        assert WikiDirectorySidecarBuilder._parse_sidecar_payload(raw) == expected


def test_parse_sidecar_payload_requires_both_fields() -> None:
    """Object missing either field is rejected, preserving the contract."""
    assert WikiDirectorySidecarBuilder._parse_sidecar_payload('{"abstract": "A"}') is None
    assert WikiDirectorySidecarBuilder._parse_sidecar_payload('{"overview": "O"}') is None
    assert WikiDirectorySidecarBuilder._parse_sidecar_payload("not json at all") is None
    assert WikiDirectorySidecarBuilder._parse_sidecar_payload("") is None


def test_extract_truth_falls_back_to_full_content() -> None:
    assert WikiDirectorySidecarBuilder._extract_truth("no compiled block here") == "no compiled block here"
    truth = WikiDirectorySidecarBuilder._extract_truth(
        "## Compiled Truth\nFacts.\n\n## Related\nOther."
    )
    assert truth == "## Compiled Truth\nFacts."


def test_extract_compact_summary_truncates_at_limit() -> None:
    text = "word " * 200
    summary = WikiDirectorySidecarBuilder._extract_compact_summary(text, max_chars=50)
    assert len(summary) <= 50


def test_clip_text_truncation_with_and_without_space() -> None:
    long_space = WikiDirectorySidecarBuilder._clip_text("one two three four", 6)
    assert long_space.endswith("…")
    long_nospace = WikiDirectorySidecarBuilder._clip_text("x" * 40, 10)
    assert long_nospace.endswith("…")
    assert len(long_nospace) == 11
    assert WikiDirectorySidecarBuilder._clip_text("short", 100) == "short"


def test_iter_parent_chain_includes_root() -> None:
    chain = WikiDirectorySidecarBuilder._iter_parent_chain("")
    assert chain == [""]
    assert WikiDirectorySidecarBuilder._iter_parent_chain("Ops/Run") == ["Ops/Run", "Ops", ""]


def test_immediate_child_dirs_root_and_nested() -> None:
    children = WikiDirectorySidecarBuilder._immediate_child_dirs("", {"a", "b", "b/c", "d/e/f"})
    assert children == ["a", "b"]
    nested = WikiDirectorySidecarBuilder._immediate_child_dirs("b", {"b", "b/c", "b/c/d", "x"})
    assert nested == ["b/c"]


def test_read_state_tolerates_dirty_payload(tmp_path):
    structure = WikiStructure(tmp_path)
    structure.ensure_structure()
    builder = WikiDirectorySidecarBuilder(AsyncMock(), structure, WikiCompileConfig())
    state_path = builder._state_path
    state_path.parent.mkdir(parents=True, exist_ok=True)

    state_path.write_text("garbage", encoding="utf-8")
    assert builder._read_state() == {}

    state_path.write_text('{"signatures": "not-a-dict"}', encoding="utf-8")
    assert builder._read_state() == {}

    state_path.write_text('{"signatures": {"__root__": 123}}', encoding="utf-8")
    assert builder._read_state() == {}

    state_path.write_text('{"signatures": {"__root__": "sig"}}', encoding="utf-8")
    assert builder._read_state() == {"": "sig"}


def test_collect_file_semantics_skips_public_mounted(tmp_path, monkeypatch):
    structure = WikiStructure(tmp_path)
    structure.ensure_structure()
    builder = WikiDirectorySidecarBuilder(AsyncMock(), structure, WikiCompileConfig())

    outside = tmp_path / "outside" / "notes.md"
    outside.parent.mkdir(exist_ok=True)
    outside.write_text("## Compiled Truth\nFacts.", encoding="utf-8")

    monkeypatch.setattr(builder._structure, "list_concepts", lambda: [outside])
    assert builder._collect_file_semantics() == []


@pytest.mark.asyncio
async def test_generate_sidecar_pair_empty_inputs_and_llm_failure(tmp_path):
    structure = WikiStructure(tmp_path)
    structure.ensure_structure()
    llm = AsyncMock(side_effect=RuntimeError("llm down"))
    builder = WikiDirectorySidecarBuilder(llm, structure, WikiCompileConfig())

    abstract, overview = await builder._generate_sidecar_pair(
        directory="ops", file_summaries=[], child_abstracts=[]
    )
    assert abstract == "No validated knowledge yet for this directory."

    abstract, overview = await builder._generate_sidecar_pair(
        directory="ops",
        file_summaries=["run: steps"],
        child_abstracts=["child: overview"],
    )
    assert "run: steps" in abstract
    assert "child: overview" in overview


@pytest.mark.asyncio
async def test_upsert_sidecar_index_variants(tmp_path, caplog):
    structure = WikiStructure(tmp_path)
    structure.ensure_structure()
    builder = WikiDirectorySidecarBuilder(AsyncMock(), structure, WikiCompileConfig())

    await builder._upsert_sidecar_index("ops", "a", "o")

    builder._indexer = object()
    await builder._upsert_sidecar_index("ops", "a", "o")

    class _BoomIndexer:
        async def upsert_sidecar(self, *_args, **_kwargs) -> None:
            raise RuntimeError("index down")

    builder._indexer = _BoomIndexer()
    await builder._upsert_sidecar_index("ops", "a", "o")


@pytest.mark.asyncio
async def test_remove_stale_sidecars_deletes_files_and_index(tmp_path):
    structure = WikiStructure(tmp_path)
    structure.ensure_structure()
    indexer = _FakeIndexer()
    builder = WikiDirectorySidecarBuilder(AsyncMock(), structure, WikiCompileConfig(), indexer=indexer)

    abstract_path, overview_path = structure.get_directory_sidecar_paths("ops", create=False)
    abstract_path.parent.mkdir(parents=True, exist_ok=True)
    abstract_path.write_text("a", encoding="utf-8")
    overview_path.write_text("o", encoding="utf-8")

    removed = await builder._remove_stale_sidecars({"ops"})
    assert removed == 2
    assert not abstract_path.exists()
    assert indexer.deletes == [("ops", 0), ("ops", 1)]
