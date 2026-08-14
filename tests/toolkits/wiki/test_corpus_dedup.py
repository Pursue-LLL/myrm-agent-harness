"""Tests for wiki raw corpus deduplication."""

from __future__ import annotations

from pathlib import Path

import pytest

from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure
from myrm_agent_harness.toolkits.wiki.pipeline.corpus_dedup import (
    CorpusDedupGovernor,
    CorpusDedupScanner,
    CorpusEligibilityFilter,
    DedupTier,
    DispositionAction,
    GroupStatus,
)
from myrm_agent_harness.toolkits.wiki.pipeline.queue import WikiIngestionQueue


@pytest.fixture
def wiki_structure(tmp_path: Path) -> WikiStructure:
    structure = WikiStructure(tmp_path / "wiki")
    structure.ensure_structure()
    return structure


def _write_raw(structure: WikiStructure, relative_path: str, content: str) -> Path:
    path = structure.get_raw_file_path(relative_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def test_scan_finds_exact_duplicate_group(wiki_structure: WikiStructure) -> None:
    content = "# Same note\n\nShared body for dedup test."
    _write_raw(wiki_structure, "notes/a.md", content)
    _write_raw(wiki_structure, "archive/a-copy.md", content)

    scanner = CorpusDedupScanner(wiki_structure)
    result = scanner.scan()

    assert result.files_scanned == 2
    assert result.exact_groups == 1
    groups = scanner.store.list_groups(status=GroupStatus.OPEN)
    assert len(groups) == 1
    assert groups[0].tier == DedupTier.EXACT
    assert len(groups[0].members) == 2


def test_exclude_filters_compile_queue(wiki_structure: WikiStructure) -> None:
    _write_raw(wiki_structure, "one.md", "# One")
    _write_raw(wiki_structure, "two.md", "# Two")
    scanner = CorpusDedupScanner(wiki_structure)
    result = scanner.scan()
    assert result.groups_found == 0

    eligibility = CorpusEligibilityFilter(wiki_structure)
    eligibility.store.add_excluded_path("two.md", reason="manual exclude")
    queue = WikiIngestionQueue(wiki_structure)
    queue.add_batch(wiki_structure.list_raw_files())
    pending = queue.list_pending_file_paths()
    assert len(pending) == 1
    assert pending[0].endswith("one.md")


def test_incremental_scan_skips_regroup_when_cache_hit(
    wiki_structure: WikiStructure,
) -> None:
    content = "# Cached note\n\nBody for incremental dedup."
    _write_raw(wiki_structure, "cached/a.md", content)
    scanner = CorpusDedupScanner(wiki_structure)
    first = scanner.scan(incremental=False)
    assert first.files_scanned == 1

    second = scanner.scan(incremental=True)
    assert second.incremental is True
    assert second.exact_groups == 0
    assert second.normalized_groups == 0
    assert second.near_groups == 0
    assert scanner.store.get_last_scan_at() is not None


@pytest.mark.asyncio
async def test_trash_moves_file_to_corpus_trash(wiki_structure: WikiStructure) -> None:
    content = "# Dup A\n\nBody"
    _write_raw(wiki_structure, "a.md", content)
    _write_raw(wiki_structure, "b.md", content)
    scanner = CorpusDedupScanner(wiki_structure)
    scanner.scan()
    group = scanner.store.list_groups(status=GroupStatus.OPEN)[0]
    governor = CorpusDedupGovernor(wiki_structure)
    duplicate_path = next(
        member.relative_path for member in group.members if member.relative_path != group.recommended_keep_path
    )
    result = await governor.apply_disposition(
        group.group_id,
        DispositionAction.TRASH,
        reason="duplicate trash test",
    )
    assert duplicate_path in result.affected_paths
    assert not wiki_structure.get_raw_file_path(duplicate_path).exists()
    trash_dir = wiki_structure.base_dir / ".corpus_trash"
    assert any(trash_dir.iterdir())


@pytest.mark.asyncio
async def test_deferred_group_persists_after_rescan(
    wiki_structure: WikiStructure,
) -> None:
    content = "# Deferred dup\n\nSame body for defer persistence."
    _write_raw(wiki_structure, "notes/a.md", content)
    _write_raw(wiki_structure, "backup/a-copy.md", content)
    scanner = CorpusDedupScanner(wiki_structure)
    scanner.scan(incremental=False)
    group = scanner.store.list_groups(status=GroupStatus.OPEN)[0]
    governor = CorpusDedupGovernor(wiki_structure)
    await governor.apply_disposition(group.group_id, DispositionAction.DEFER, reason="")
    deferred = scanner.store.list_groups(status=GroupStatus.DEFERRED)
    assert len(deferred) == 1

    _write_raw(wiki_structure, "new-note.md", "# Unrelated\n\nTriggers regroup.")
    scanner.scan(incremental=False)
    deferred_after = scanner.store.list_groups(status=GroupStatus.DEFERRED)
    assert len(deferred_after) == 1
    assert {member.relative_path for member in deferred_after[0].members} == {
        member.relative_path for member in group.members
    }


@pytest.mark.asyncio
async def test_restore_trashed_raw_returns_file_to_raw_dir(
    wiki_structure: WikiStructure,
) -> None:
    content = "# Restore me\n\nBody"
    _write_raw(wiki_structure, "keep.md", content)
    _write_raw(wiki_structure, "trash-me.md", content)
    scanner = CorpusDedupScanner(wiki_structure)
    scanner.scan()
    group = scanner.store.list_groups(status=GroupStatus.OPEN)[0]
    governor = CorpusDedupGovernor(wiki_structure)
    trash_path = next(
        member.relative_path for member in group.members if member.relative_path != group.recommended_keep_path
    )
    await governor.apply_disposition(group.group_id, DispositionAction.TRASH, reason="restore test")
    assert not wiki_structure.get_raw_file_path(trash_path).exists()

    restored = await governor.restore_trashed_raw(trash_path)
    assert restored.relative_path == trash_path
    assert wiki_structure.get_raw_file_path(trash_path).exists()
    assert governor.list_vault_hygiene().trashed == ()


@pytest.mark.asyncio
async def test_undo_excluded_raw_re_enables_compile_eligibility(
    wiki_structure: WikiStructure,
) -> None:
    content = "# Exclude undo\n\nBody"
    _write_raw(wiki_structure, "one.md", content)
    _write_raw(wiki_structure, "two.md", content)
    scanner = CorpusDedupScanner(wiki_structure)
    scanner.scan()
    group = scanner.store.list_groups(status=GroupStatus.OPEN)[0]
    governor = CorpusDedupGovernor(wiki_structure)
    exclude_path = next(
        member.relative_path for member in group.members if member.relative_path != group.recommended_keep_path
    )
    await governor.apply_disposition(group.group_id, DispositionAction.EXCLUDE, reason="exclude undo test")
    eligibility = CorpusEligibilityFilter(wiki_structure)
    assert not eligibility.is_eligible_relative_path(exclude_path)

    governor.undo_excluded_raw(exclude_path)
    assert eligibility.is_eligible_relative_path(exclude_path)
    assert governor.list_vault_hygiene().excluded == ()


def test_deferred_group_stays_deferred_when_cluster_grows(
    wiki_structure: WikiStructure,
) -> None:
    content = "# Deferred growth\n\nSame body for growing defer cluster."
    _write_raw(wiki_structure, "notes/a.md", content)
    _write_raw(wiki_structure, "backup/a-copy.md", content)
    scanner = CorpusDedupScanner(wiki_structure)
    scanner.scan(incremental=False)
    group = scanner.store.list_groups(status=GroupStatus.OPEN)[0]
    scanner.store.update_group_status(group.group_id, GroupStatus.DEFERRED)

    _write_raw(wiki_structure, "imports/a-third.md", content)
    scanner.scan(incremental=False)
    deferred_after = scanner.store.list_groups(status=GroupStatus.DEFERRED)
    assert len(deferred_after) == 1
    assert len(deferred_after[0].members) == 3


@pytest.mark.asyncio
async def test_restore_trashed_raw_re_enqueues_compile(
    wiki_structure: WikiStructure,
) -> None:
    content = "# Restore enqueue\n\nBody"
    _write_raw(wiki_structure, "keep.md", content)
    _write_raw(wiki_structure, "trash-me.md", content)
    scanner = CorpusDedupScanner(wiki_structure)
    scanner.scan()
    group = scanner.store.list_groups(status=GroupStatus.OPEN)[0]
    governor = CorpusDedupGovernor(wiki_structure)
    trash_path = next(
        member.relative_path for member in group.members if member.relative_path != group.recommended_keep_path
    )

    class _FakeCompiler:
        def __init__(self) -> None:
            self.enqueued: list[Path] = []

        def enqueue_file(self, file_path: Path) -> None:
            self.enqueued.append(file_path)

    compiler = _FakeCompiler()
    await governor.apply_disposition(
        group.group_id,
        DispositionAction.TRASH,
        reason="restore enqueue test",
        compiler=compiler,
    )
    assert not wiki_structure.get_raw_file_path(trash_path).exists()
    queued_before_restore = len(compiler.enqueued)

    await governor.restore_trashed_raw(trash_path, compiler=compiler)
    restored_raw = wiki_structure.get_raw_file_path(trash_path)
    assert restored_raw.exists()
    assert len(compiler.enqueued) == queued_before_restore + 1
    assert restored_raw in compiler.enqueued


@pytest.mark.asyncio
async def test_fully_dismissed_group_stays_hidden_on_rescan(
    wiki_structure: WikiStructure,
) -> None:
    content = "# Dismiss hidden\n\nSame body stays dismissed after rescan."
    _write_raw(wiki_structure, "notes/a.md", content)
    _write_raw(wiki_structure, "backup/a-copy.md", content)
    scanner = CorpusDedupScanner(wiki_structure)
    scanner.scan(incremental=False)
    group = scanner.store.list_groups(status=GroupStatus.OPEN)[0]
    governor = CorpusDedupGovernor(wiki_structure)
    await governor.apply_disposition(group.group_id, DispositionAction.DISMISS, reason="")

    scanner.scan(incremental=False)
    open_groups = scanner.store.list_groups(status=GroupStatus.OPEN)
    assert open_groups == []


@pytest.mark.asyncio
async def test_dismissed_group_resurfaces_when_new_member_joins(
    wiki_structure: WikiStructure,
) -> None:
    content = "# Dismiss regroup\n\nSame body for dismiss regroup test."
    _write_raw(wiki_structure, "notes/a.md", content)
    _write_raw(wiki_structure, "backup/a-copy.md", content)
    _write_raw(wiki_structure, "archive/a-old.md", content)
    scanner = CorpusDedupScanner(wiki_structure)
    scanner.scan(incremental=False)
    group = scanner.store.list_groups(status=GroupStatus.OPEN)[0]
    governor = CorpusDedupGovernor(wiki_structure)
    await governor.apply_disposition(group.group_id, DispositionAction.DISMISS, reason="")

    _write_raw(wiki_structure, "imports/new-dup.md", content)
    scanner.scan(incremental=False)
    open_groups = scanner.store.list_groups(status=GroupStatus.OPEN)
    assert len(open_groups) == 1
    assert {member.relative_path for member in open_groups[0].members} == {
        "notes/a.md",
        "backup/a-copy.md",
        "archive/a-old.md",
        "imports/new-dup.md",
    }


def test_build_group_body_snippets_returns_comparable_excerpt(
    wiki_structure: WikiStructure,
) -> None:
    from myrm_agent_harness.toolkits.wiki.pipeline.corpus_dedup.snippets import (
        build_group_body_snippets,
    )

    long_body = "word " * 120
    _write_raw(wiki_structure, "a.md", f"# Title\n\n{long_body}")
    _write_raw(wiki_structure, "b.md", f"# Title\n\n{long_body}")
    scanner = CorpusDedupScanner(wiki_structure)
    scanner.scan()
    group = scanner.store.list_groups(status=GroupStatus.OPEN)[0]
    snippets = build_group_body_snippets(wiki_structure, group, max_chars=80)
    assert len(snippets) == 2
    assert all(item.snippet.endswith("…") for item in snippets)
    assert snippets[0].snippet == snippets[1].snippet


def test_scan_finds_normalized_duplicate_group(wiki_structure: WikiStructure) -> None:
    _write_raw(wiki_structure, "note.md", "# Title\n\nSame normalized body.")
    _write_raw(wiki_structure, "page.md", "<h1>Title</h1><p>Same normalized body.</p>")
    scanner = CorpusDedupScanner(wiki_structure)
    result = scanner.scan(incremental=False)
    assert result.normalized_groups == 1
    groups = scanner.store.list_groups(status=GroupStatus.OPEN)
    assert groups[0].tier == DedupTier.NORMALIZED


def test_scan_finds_near_duplicate_group(wiki_structure: WikiStructure) -> None:
    shared = "the quick brown fox jumps over the lazy dog "
    _write_raw(wiki_structure, "near-a.md", f"# Near A\n\n{shared * 12}end")
    _write_raw(wiki_structure, "near-b.md", f"# Near B\n\n{shared * 12}ends")
    scanner = CorpusDedupScanner(wiki_structure)
    result = scanner.scan(incremental=False)
    assert result.near_groups == 1
    assert scanner.store.list_groups(status=GroupStatus.OPEN)[0].tier == DedupTier.NEAR


def test_eligibility_filter_relative_paths_and_count(
    wiki_structure: WikiStructure,
) -> None:
    _write_raw(wiki_structure, "keep.md", "# keep")
    _write_raw(wiki_structure, "drop.md", "# drop")
    eligibility = CorpusEligibilityFilter(wiki_structure)
    eligibility.store.add_excluded_path("drop.md", reason="test")
    assert eligibility.count_eligible_raw_files() == 1
    assert eligibility.filter_relative_paths(["keep.md", "drop.md"]) == ["keep.md"]
    assert eligibility.is_eligible_raw_file(wiki_structure.get_raw_file_path("keep.md")) is True
    assert eligibility.is_eligible_relative_path("drop.md") is False


def test_blocking_open_groups_excludes_near_tier(wiki_structure: WikiStructure) -> None:
    shared = "the quick brown fox jumps over the lazy dog "
    _write_raw(wiki_structure, "near-a.md", f"# Near A\n\n{shared * 12}end")
    _write_raw(wiki_structure, "near-b.md", f"# Near B\n\n{shared * 12}ends")
    scanner = CorpusDedupScanner(wiki_structure)
    scanner.scan(incremental=False)
    governor = CorpusDedupGovernor(wiki_structure)
    assert governor.blocking_open_groups() == []


@pytest.mark.asyncio
async def test_governor_apply_disposition_unknown_group_raises(
    wiki_structure: WikiStructure,
) -> None:
    governor = CorpusDedupGovernor(wiki_structure)
    with pytest.raises(ValueError, match="Duplicate group not found"):
        await governor.apply_disposition(999_999, DispositionAction.DISMISS, reason="")


def test_normalize_raw_relative_path_strips_leading_slash() -> None:
    from myrm_agent_harness.toolkits.wiki.pipeline.corpus_dedup.path_utils import (
        normalize_raw_relative_path,
    )

    assert normalize_raw_relative_path("/notes/a.md") == "notes/a.md"
    assert normalize_raw_relative_path("notes\\b.md") == "notes/b.md"
