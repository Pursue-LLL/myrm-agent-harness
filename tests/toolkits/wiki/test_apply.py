"""Tests for wiki narrow-write apply pipeline."""

from __future__ import annotations

from pathlib import Path

import pytest

from myrm_agent_harness.toolkits.wiki.core.section_contract import (
    COMPILED_TRUTH_HEADING,
    TIMELINE_HEADING,
)
from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure
from myrm_agent_harness.toolkits.wiki.pipeline.apply import (
    WikiApplyError,
    WikiApplyOp,
    WikiApplyRequest,
    apply_wiki_mutation,
)
from myrm_agent_harness.toolkits.wiki.retrieval.indexer import WikiIndexer


@pytest.fixture
def wiki_structure(tmp_path: Path) -> WikiStructure:
    structure = WikiStructure(tmp_path / "wiki")
    structure.ensure_structure()
    return structure


def _sample_content() -> str:
    return (
        "---\n"
        "type: concept\n"
        "tags:\n"
        "  - alpha\n"
        "claims:\n"
        "  - id: claim.sample.summary\n"
        "    text: Old summary\n"
        "    status: unknown\n"
        "    confidence: 0.5\n"
        "    evidence: []\n"
        "---\n"
        f"{COMPILED_TRUTH_HEADING}\n"
        "Old summary\n\n"
        f"{TIMELINE_HEADING}\n"
        "- first event\n"
    )


@pytest.mark.asyncio
async def test_create_note_builds_managed_sections(wiki_structure: WikiStructure) -> None:
    indexer = WikiIndexer(wiki_structure)
    result = await apply_wiki_mutation(
        wiki_structure,
        indexer,
        WikiApplyRequest(
            op=WikiApplyOp.CREATE_NOTE,
            concept_name="chat/saved-note",
            body="Saved assistant answer",
            metadata={"source_chat": "chat-1", "source_message": "msg-1"},
            provenance="chat-save",
        ),
        caller="agent",
    )
    assert result.created is True
    content = wiki_structure.get_concept_file_path("chat/saved-note").read_text(encoding="utf-8")
    assert "type: session" in content
    assert "Saved assistant answer" in content
    assert TIMELINE_HEADING in content
    assert "claims:" in content


@pytest.mark.asyncio
async def test_patch_compiled_truth_preserves_timeline(wiki_structure: WikiStructure) -> None:
    path = wiki_structure.get_concept_file_path("physics/gravity")
    path.write_text(_sample_content(), encoding="utf-8")
    indexer = WikiIndexer(wiki_structure)

    result = await apply_wiki_mutation(
        wiki_structure,
        indexer,
        WikiApplyRequest(
            op=WikiApplyOp.PATCH_COMPILED_TRUTH,
            concept_name="physics/gravity",
            compiled_truth="Updated gravity summary",
        ),
        caller="agent",
    )

    assert result.success is True
    content = path.read_text(encoding="utf-8")
    assert "Updated gravity summary" in content
    assert "- first event" in content
    assert "claim.physics.gravity.summary" in content or "Updated gravity summary" in content


@pytest.mark.asyncio
async def test_append_timeline_skips_duplicate(wiki_structure: WikiStructure) -> None:
    path = wiki_structure.get_concept_file_path("physics/gravity")
    path.write_text(_sample_content(), encoding="utf-8")
    indexer = WikiIndexer(wiki_structure)

    first = await apply_wiki_mutation(
        wiki_structure,
        indexer,
        WikiApplyRequest(
            op=WikiApplyOp.APPEND_TIMELINE,
            concept_name="physics/gravity",
            timeline_entry="second event",
        ),
        caller="settings",
    )
    assert first.appended is True

    second = await apply_wiki_mutation(
        wiki_structure,
        indexer,
        WikiApplyRequest(
            op=WikiApplyOp.APPEND_TIMELINE,
            concept_name="physics/gravity",
            timeline_entry="second event",
        ),
        caller="settings",
    )
    assert second.appended is False


@pytest.mark.asyncio
async def test_update_metadata_merges_tags(wiki_structure: WikiStructure) -> None:
    path = wiki_structure.get_concept_file_path("physics/gravity")
    path.write_text(_sample_content(), encoding="utf-8")
    indexer = WikiIndexer(wiki_structure)

    await apply_wiki_mutation(
        wiki_structure,
        indexer,
        WikiApplyRequest(
            op=WikiApplyOp.UPDATE_METADATA,
            concept_name="physics/gravity",
            tags=("beta",),
            aliases=("Gravity",),
        ),
        caller="settings",
    )

    content = path.read_text(encoding="utf-8")
    assert "beta" in content
    assert "Gravity" in content
    assert "alpha" not in content


@pytest.mark.asyncio
async def test_agent_forbidden_full_replace(wiki_structure: WikiStructure) -> None:
    path = wiki_structure.get_concept_file_path("physics/gravity")
    path.write_text(_sample_content(), encoding="utf-8")
    indexer = WikiIndexer(wiki_structure)

    with pytest.raises(WikiApplyError) as exc:
        await apply_wiki_mutation(
            wiki_structure,
            indexer,
            WikiApplyRequest(
                op=WikiApplyOp.REPLACE_FULL_DOCUMENT,
                concept_name="physics/gravity",
                content=_sample_content(),
            ),
            caller="agent",
        )
    assert exc.value.code == "forbidden_for_caller"


@pytest.mark.asyncio
async def test_chat_forbidden_full_replace(wiki_structure: WikiStructure) -> None:
    path = wiki_structure.get_concept_file_path("physics/gravity")
    path.write_text(_sample_content(), encoding="utf-8")
    indexer = WikiIndexer(wiki_structure)

    with pytest.raises(WikiApplyError) as exc:
        await apply_wiki_mutation(
            wiki_structure,
            indexer,
            WikiApplyRequest(
                op=WikiApplyOp.REPLACE_FULL_DOCUMENT,
                concept_name="physics/gravity",
                content=_sample_content(),
            ),
            caller="chat",
        )
    assert exc.value.code == "forbidden_for_caller"


@pytest.mark.asyncio
async def test_parse_editor_sections_reads_yaml_list_tags() -> None:
    from myrm_agent_harness.toolkits.wiki.core.section_contract import parse_editor_sections

    content = (
        "---\n"
        "type: concept\n"
        "tags:\n"
        "  - alpha\n"
        "  - beta\n"
        "aliases:\n"
        "  - Gravity\n"
        "---\n"
        "## Compiled Truth\n"
        "Summary line\n\n"
        "## Timeline\n"
        "- first event\n"
    )
    sections = parse_editor_sections(content)
    assert sections.compiled_truth == "Summary line"
    assert "first event" in sections.timeline
    assert sections.tags == ("alpha", "beta")
    assert sections.aliases == ("Gravity",)


@pytest.mark.asyncio
async def test_create_note_canonical_conflict_on_alias(wiki_structure: WikiStructure) -> None:
    content_with_alias = (
        "---\n"
        "type: concept\n"
        "aliases:\n"
        "  - React Hooks\n"
        "---\n"
        f"{COMPILED_TRUTH_HEADING}\n"
        "Existing page\n\n"
        f"{TIMELINE_HEADING}\n"
        "- seeded\n"
    )
    path = wiki_structure.get_concept_file_path("topics/react-hooks")
    path.write_text(content_with_alias, encoding="utf-8")
    indexer = WikiIndexer(wiki_structure)

    with pytest.raises(WikiApplyError) as exc:
        await apply_wiki_mutation(
            wiki_structure,
            indexer,
            WikiApplyRequest(
                op=WikiApplyOp.CREATE_NOTE,
                concept_name="notes/hooks-guide",
                body="Duplicate topic",
                aliases=("React Hooks",),
            ),
            caller="agent",
        )
    assert exc.value.code == "canonical_conflict"


@pytest.mark.asyncio
async def test_if_match_conflict(wiki_structure: WikiStructure) -> None:
    path = wiki_structure.get_concept_file_path("physics/gravity")
    path.write_text(_sample_content(), encoding="utf-8")
    indexer = WikiIndexer(wiki_structure)

    with pytest.raises(WikiApplyError) as exc:
        await apply_wiki_mutation(
            wiki_structure,
            indexer,
            WikiApplyRequest(
                op=WikiApplyOp.PATCH_COMPILED_TRUTH,
                concept_name="physics/gravity",
                compiled_truth="Changed elsewhere",
                if_match="deadbeef",
            ),
            caller="settings",
        )
    assert exc.value.code == "conflict"


@pytest.mark.asyncio
async def test_create_note_conflicts_when_exists(wiki_structure: WikiStructure) -> None:
    path = wiki_structure.get_concept_file_path("dup")
    path.write_text(_sample_content(), encoding="utf-8")
    indexer = WikiIndexer(wiki_structure)

    with pytest.raises(WikiApplyError) as exc:
        await apply_wiki_mutation(
            wiki_structure,
            indexer,
            WikiApplyRequest(
                op=WikiApplyOp.CREATE_NOTE,
                concept_name="dup",
                body="new",
            ),
            caller="agent",
        )
    assert exc.value.code == "concept_exists"
