"""Tests for wiki raw publication gate."""

from __future__ import annotations

from pathlib import Path

import pytest

from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure
from myrm_agent_harness.toolkits.wiki.pipeline.raw_gate import (
    RawConflictPolicy,
    RawGateError,
    RawPublishRequest,
    publish_raw,
)


@pytest.fixture
def wiki_structure(tmp_path: Path) -> WikiStructure:
    structure = WikiStructure(tmp_path / "wiki")
    structure.ensure_structure()
    return structure


@pytest.mark.asyncio
async def test_publish_raw_creates_new_file(wiki_structure: WikiStructure) -> None:
    result = await publish_raw(
        wiki_structure,
        RawPublishRequest(
            relative_path="notes/hello.md",
            content="# Hello\n",
            conflict_policy=RawConflictPolicy.FAIL,
        ),
        caller="agent",
    )
    assert result.created is True
    assert result.written is True
    assert result.skipped is False
    assert wiki_structure.get_raw_file_path("notes/hello.md").read_text(encoding="utf-8") == "# Hello\n"


@pytest.mark.asyncio
async def test_publish_raw_skip_on_conflict(wiki_structure: WikiStructure) -> None:
    raw_path = wiki_structure.get_raw_file_path("notes/conflict.md")
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_text("original", encoding="utf-8")

    result = await publish_raw(
        wiki_structure,
        RawPublishRequest(
            relative_path="notes/conflict.md",
            content="replacement",
            conflict_policy=RawConflictPolicy.SKIP,
        ),
        caller="settings",
    )
    assert result.skipped is True
    assert result.conflict_skipped is True
    assert result.written is False
    assert raw_path.read_text(encoding="utf-8") == "original"


@pytest.mark.asyncio
async def test_publish_raw_supersede_with_audit_log(wiki_structure: WikiStructure) -> None:
    raw_path = wiki_structure.get_raw_file_path("notes/supersede.md")
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_text("old body", encoding="utf-8")

    result = await publish_raw(
        wiki_structure,
        RawPublishRequest(
            relative_path="notes/supersede.md",
            content="new body",
            conflict_policy=RawConflictPolicy.SUPERSEDE,
            supersede_reason="Re-import from Obsidian vault",
        ),
        caller="settings",
    )
    assert result.superseded is True
    assert result.written is True
    assert raw_path.read_text(encoding="utf-8") == "new body"

    log_text = wiki_structure.get_log_file_path().read_text(encoding="utf-8")
    assert "raw_supersede" in log_text or "Superseded raw source" in log_text


@pytest.mark.asyncio
async def test_publish_raw_fail_for_agent_conflict(wiki_structure: WikiStructure) -> None:
    raw_path = wiki_structure.get_raw_file_path("notes/agent-block.md")
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_text("existing", encoding="utf-8")

    with pytest.raises(RawGateError) as exc_info:
        await publish_raw(
            wiki_structure,
            RawPublishRequest(
                relative_path="notes/agent-block.md",
                content="different",
                conflict_policy=RawConflictPolicy.FAIL,
            ),
            caller="agent",
        )
    assert exc_info.value.code == "raw_conflict"


@pytest.mark.asyncio
async def test_publish_raw_idempotent_same_hash(wiki_structure: WikiStructure) -> None:
    content = "stable content"
    raw_path = wiki_structure.get_raw_file_path("notes/stable.md")
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_text(content, encoding="utf-8")

    result = await publish_raw(
        wiki_structure,
        RawPublishRequest(
            relative_path="notes/stable.md",
            content=content,
            conflict_policy=RawConflictPolicy.SKIP,
        ),
        caller="settings",
    )
    assert result.skipped is True
    assert result.conflict_skipped is False
    assert result.written is False


@pytest.mark.asyncio
async def test_publish_raw_put_if_absent(wiki_structure: WikiStructure) -> None:
    result = await publish_raw(
        wiki_structure,
        RawPublishRequest(
            relative_path="archive/query.md",
            content="query snapshot",
            conflict_policy=RawConflictPolicy.PUT_IF_ABSENT,
        ),
        caller="agent",
    )
    assert result.created is True

    second = await publish_raw(
        wiki_structure,
        RawPublishRequest(
            relative_path="archive/query.md",
            content="other snapshot",
            conflict_policy=RawConflictPolicy.PUT_IF_ABSENT,
        ),
        caller="agent",
    )
    assert second.conflict_skipped is True
    assert wiki_structure.get_raw_file_path("archive/query.md").read_text(encoding="utf-8") == "query snapshot"


@pytest.mark.asyncio
async def test_publish_raw_rejects_parent_traversal(wiki_structure: WikiStructure) -> None:
    with pytest.raises(RawGateError) as exc_info:
        await publish_raw(
            wiki_structure,
            RawPublishRequest(
                relative_path="../../outside.md",
                content="# escape\n",
                conflict_policy=RawConflictPolicy.FAIL,
            ),
            caller="agent",
        )
    assert exc_info.value.code == "invalid_path"


@pytest.mark.asyncio
async def test_publish_raw_rejects_traversal_in_subfolder(wiki_structure: WikiStructure) -> None:
    with pytest.raises(RawGateError) as exc_info:
        await publish_raw(
            wiki_structure,
            RawPublishRequest(
                relative_path="notes/../../etc/cron.d/evil.md",
                content="# escape\n",
                conflict_policy=RawConflictPolicy.FAIL,
            ),
            caller="agent",
        )
    assert exc_info.value.code == "invalid_path"


@pytest.mark.asyncio
async def test_publish_raw_rejects_drive_prefix(wiki_structure: WikiStructure) -> None:
    with pytest.raises(RawGateError) as exc_info:
        await publish_raw(
            wiki_structure,
            RawPublishRequest(
                relative_path="C:/outside.md",
                content="# escape\n",
                conflict_policy=RawConflictPolicy.FAIL,
            ),
            caller="agent",
        )
    assert exc_info.value.code == "invalid_path"


@pytest.mark.asyncio
async def test_publish_raw_rejects_backslash_traversal(wiki_structure: WikiStructure) -> None:
    with pytest.raises(RawGateError) as exc_info:
        await publish_raw(
            wiki_structure,
            RawPublishRequest(
                relative_path=r"..\..\outside.md",
                content="# escape\n",
                conflict_policy=RawConflictPolicy.FAIL,
            ),
            caller="agent",
        )
    assert exc_info.value.code == "invalid_path"


@pytest.mark.asyncio
async def test_publish_raw_rejects_overlong_path(wiki_structure: WikiStructure) -> None:
    with pytest.raises(RawGateError) as exc_info:
        await publish_raw(
            wiki_structure,
            RawPublishRequest(
                relative_path="notes/" + "a" * 300 + ".md",
                content="# long\n",
                conflict_policy=RawConflictPolicy.FAIL,
            ),
            caller="agent",
        )
    assert exc_info.value.code == "invalid_path"


@pytest.mark.asyncio
async def test_publish_raw_injects_metadata_into_frontmatter(
    wiki_structure: WikiStructure,
) -> None:
    result = await publish_raw(
        wiki_structure,
        RawPublishRequest(
            relative_path="notes/metadata.md",
            content="# Meta\n",
            conflict_policy=RawConflictPolicy.FAIL,
            metadata={"source_chat": "chat-abc", "compound_provenance": "auto-archive"},
        ),
        caller="agent",
    )
    assert result.created is True
    written = wiki_structure.get_raw_file_path("notes/metadata.md").read_text(encoding="utf-8")
    assert "source_chat: chat-abc" in written
    assert "compound_provenance: auto-archive" in written
    assert "# Meta" in written


@pytest.mark.asyncio
async def test_publish_raw_metadata_merges_into_existing_frontmatter(
    wiki_structure: WikiStructure,
) -> None:
    first = await publish_raw(
        wiki_structure,
        RawPublishRequest(
            relative_path="notes/merge.md",
            content="# Merge\n",
            conflict_policy=RawConflictPolicy.FAIL,
        ),
        caller="agent",
    )
    assert first.created is True

    second = await publish_raw(
        wiki_structure,
        RawPublishRequest(
            relative_path="notes/merge.md",
            content="# Merge\n",
            conflict_policy=RawConflictPolicy.SUPERSEDE,
            supersede_reason="Re-import with provenance",
            metadata={"source_chat": "chat-xyz"},
        ),
        caller="settings",
    )
    assert second.superseded is True
    written = wiki_structure.get_raw_file_path("notes/merge.md").read_text(encoding="utf-8")
    assert "source_chat: chat-xyz" in written


@pytest.mark.asyncio
async def test_publish_raw_metadata_empty_noop(wiki_structure: WikiStructure) -> None:
    result = await publish_raw(
        wiki_structure,
        RawPublishRequest(
            relative_path="notes/noop.md",
            content="# Noop\n",
            conflict_policy=RawConflictPolicy.FAIL,
        ),
        caller="agent",
    )
    assert result.created is True
    written = wiki_structure.get_raw_file_path("notes/noop.md").read_text(encoding="utf-8")
    assert "source_chat" not in written


@pytest.mark.asyncio
async def test_publish_raw_metadata_merges_keeps_existing_fields(
    wiki_structure: WikiStructure,
) -> None:
    first = await publish_raw(
        wiki_structure,
        RawPublishRequest(
            relative_path="notes/merge2.md",
            content="# Merge2\n",
            conflict_policy=RawConflictPolicy.FAIL,
            metadata={"source_chat": "chat-old", "source_url": "https://example.com/a"},
        ),
        caller="agent",
    )
    assert first.created is True

    second = await publish_raw(
        wiki_structure,
        RawPublishRequest(
            relative_path="notes/merge2.md",
            content="# Merge2\n",
            conflict_policy=RawConflictPolicy.SUPERSEDE,
            supersede_reason="Re-import with provenance",
            metadata={"source_chat": "chat-new"},
        ),
        caller="settings",
    )
    assert second.superseded is True
    written = wiki_structure.get_raw_file_path("notes/merge2.md").read_text(encoding="utf-8")
    assert "source_chat: chat-new" in written
    assert "https://example.com/a" in written


@pytest.mark.asyncio
async def test_publish_raw_metadata_merges_new_content_frontmatter(
    wiki_structure: WikiStructure,
) -> None:
    """New content carrying its own frontmatter must not produce a double block."""
    content = "---\nweb_metadata:\n  title: Example\n---\n# Body\n"
    result = await publish_raw(
        wiki_structure,
        RawPublishRequest(
            relative_path="notes/merge3.md",
            content=content,
            conflict_policy=RawConflictPolicy.FAIL,
            metadata={"source_chat": "chat-meta"},
        ),
        caller="agent",
    )
    assert result.created is True
    written = wiki_structure.get_raw_file_path("notes/merge3.md").read_text(encoding="utf-8")
    assert "source_chat: chat-meta" in written
    assert "title: Example" in written
    assert written.count("---") == 2  # opening + closing fence, no duplicated block
