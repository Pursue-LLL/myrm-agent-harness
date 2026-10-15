"""LLM backlink discovery: scope, link placement, model input and write safety."""

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from myrm_agent_harness.toolkits.wiki import WikiStructure
from myrm_agent_harness.toolkits.wiki.core.related_links import RELATED_HEADING
from myrm_agent_harness.toolkits.wiki.core.section_contract import get_section_inner
from myrm_agent_harness.toolkits.wiki.diagnostics.structural_lint import collect_broken_wikilink_issues
from myrm_agent_harness.toolkits.wiki.pipeline.publication import ArticlePublishOutcome
from tests.toolkits.wiki.discovery_support import ScriptedLLM, make_linter, reply_for, write_page


@pytest.fixture
def structure(tmp_path: Path) -> WikiStructure:
    wiki = WikiStructure(tmp_path / "wiki-root")
    wiki.ensure_structure()
    return wiki


@pytest.mark.asyncio
async def test_link_lands_in_the_related_section_not_in_the_last_section(structure: WikiStructure) -> None:
    alpha = write_page(structure, "alpha", tail="\n## Sources\n- raw/a.md\n")
    write_page(structure, "beta")
    linter = make_linter(ScriptedLLM(reply_for("alpha", '["beta"]')), structure)

    count = await linter._discover_connections()

    saved = alpha.read_text(encoding="utf-8")
    assert count == 1
    assert "[[beta]]" in (get_section_inner(saved, RELATED_HEADING) or "")
    assert get_section_inner(saved, "## Sources") == "- raw/a.md"


@pytest.mark.asyncio
async def test_related_section_written_by_a_person_keeps_its_text(structure: WikiStructure) -> None:
    alpha = write_page(structure, "alpha", tail="\n## Related Concepts\n\nMy own reading list.\n\n- [[Old Link]]\n")
    write_page(structure, "beta")
    linter = make_linter(ScriptedLLM(reply_for("alpha", '["beta"]')), structure)

    await linter._discover_connections()

    inner = get_section_inner(alpha.read_text(encoding="utf-8"), RELATED_HEADING) or ""
    assert "My own reading list." in inner
    assert "[[Old Link]]" in inner
    assert "[[beta]]" in inner


@pytest.mark.asyncio
async def test_same_named_pages_get_a_link_that_names_exactly_one_page(structure: WikiStructure) -> None:
    write_page(structure, "rust/overview")
    write_page(structure, "go/overview")
    intro = write_page(structure, "intro")
    llm = ScriptedLLM(reply_for("intro", '["overview", "go/overview"]'))

    count = await make_linter(llm, structure)._discover_connections()

    saved = intro.read_text(encoding="utf-8")
    assert count == 1
    assert "[[go/overview]]" in saved
    assert "[[overview]]" not in saved
    assert "- overview\n" not in llm.prompt_for("intro")
    assert collect_broken_wikilink_issues(structure) == []


@pytest.mark.asyncio
async def test_a_page_counts_one_link_however_the_model_spells_it(structure: WikiStructure) -> None:
    alpha = write_page(structure, "alpha")
    write_page(structure, "beta")
    llm = ScriptedLLM(reply_for("alpha", '["beta", "Beta", "BETA"]'))

    count = await make_linter(llm, structure)._discover_connections()

    assert count == 1
    assert alpha.read_text(encoding="utf-8").lower().count("[[beta]]") == 1


@pytest.mark.asyncio
async def test_a_page_the_article_already_links_is_neither_added_nor_counted(structure: WikiStructure) -> None:
    alpha = write_page(structure, "alpha", body="See [[Beta]] for details.")
    write_page(structure, "beta")
    before = alpha.read_text(encoding="utf-8")

    count = await make_linter(ScriptedLLM(reply_for("alpha", '["beta"]')), structure)._discover_connections()

    assert count == 0
    assert alpha.read_text(encoding="utf-8") == before


@pytest.mark.asyncio
async def test_a_link_the_publish_gate_refused_is_not_a_connection(
    structure: WikiStructure, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_page(structure, "alpha")
    write_page(structure, "beta")
    monkeypatch.setattr(
        "myrm_agent_harness.toolkits.wiki.maintenance.backlink_discovery.publish_concept_article",
        AsyncMock(return_value=ArticlePublishOutcome.BLOCKED),
    )

    count = await make_linter(ScriptedLLM(reply_for("alpha", '["beta"]')), structure)._discover_connections()

    assert count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["draft", "blocked"])
async def test_unpublished_pages_are_neither_rewritten_nor_offered_as_targets(
    structure: WikiStructure, status: str
) -> None:
    live = write_page(structure, "live")
    held = write_page(structure, "held", status=status)
    write_page(structure, "other")
    held_before = held.read_bytes()
    llm = ScriptedLLM('["held", "other"]')

    await make_linter(llm, structure)._discover_connections()

    assert held.read_bytes() == held_before
    assert "held" not in llm.articles()
    assert all("- held\n" not in prompt for prompt in llm.prompts)
    saved = live.read_text(encoding="utf-8")
    assert "[[other]]" in saved
    assert "[[held]]" not in saved


@pytest.mark.asyncio
async def test_template_pages_are_out_of_scope(structure: WikiStructure) -> None:
    write_page(structure, "alpha")
    write_page(structure, "beta")
    template = structure.templates_dir / "note.md"
    template.write_text("---\ntype: template\n---\n\n## Compiled Truth\n{{body}}\n", encoding="utf-8")
    template_before = template.read_bytes()
    llm = ScriptedLLM("[]")

    await make_linter(llm, structure)._discover_connections()

    assert sorted(llm.articles()) == ["alpha", "beta"]
    assert all("note" not in prompt for prompt in llm.prompts)
    assert template.read_bytes() == template_before


@pytest.mark.asyncio
async def test_a_page_publishing_cannot_address_is_linked_to_but_never_rewritten(structure: WikiStructure) -> None:
    hand_made = structure.concepts_dir / "Alpha Notes.md"
    hand_made.write_text("---\ntype: concept\n---\n\n## Compiled Truth\nAlpha.\n", encoding="utf-8")
    beta = write_page(structure, "beta")
    before = hand_made.read_bytes()
    llm = ScriptedLLM('["Alpha Notes", "beta"]')

    count = await make_linter(llm, structure)._discover_connections()

    assert count == 1
    assert "[[Alpha Notes]]" in beta.read_text(encoding="utf-8")
    assert hand_made.read_bytes() == before
    assert sorted(path.name for path in structure.concepts_dir.glob("*.md")) == ["Alpha Notes.md", "beta.md"]


@pytest.mark.asyncio
async def test_pages_of_read_only_public_mounts_are_out_of_scope(tmp_path: Path) -> None:
    public_page = tmp_path / "public" / "wiki" / "concepts" / "shared.md"
    public_page.parent.mkdir(parents=True)
    public_page.write_text("---\ntype: concept\n---\n\n## Compiled Truth\nShared.\n", encoding="utf-8")
    local = WikiStructure(tmp_path / "local", public_dirs=[tmp_path / "public"])
    local.ensure_structure()
    write_page(local, "alpha")
    write_page(local, "beta")
    llm = ScriptedLLM(reply_for("alpha", '["beta", "shared"]'))

    count = await make_linter(llm, local)._discover_connections()

    assert count == 1
    assert sorted(llm.articles()) == ["alpha", "beta"]
    assert all("shared" not in prompt for prompt in llm.prompts)


@pytest.mark.asyncio
async def test_looking_at_a_hand_made_folder_creates_no_folder(structure: WikiStructure) -> None:
    page = structure.concepts_dir / "Work Notes" / "Alpha Page.md"
    page.parent.mkdir()
    page.write_text("---\ntype: concept\n---\n\n## Compiled Truth\nAlpha.\n", encoding="utf-8")
    write_page(structure, "beta")
    folders_before = sorted(path.name for path in structure.concepts_dir.iterdir() if path.is_dir())

    await make_linter(ScriptedLLM("[]"), structure)._discover_connections()

    assert sorted(path.name for path in structure.concepts_dir.iterdir() if path.is_dir()) == folders_before


@pytest.mark.asyncio
async def test_a_page_named_only_by_case_never_gains_a_case_variant_sibling(structure: WikiStructure) -> None:
    hand_made = structure.concepts_dir / "Beta.md"
    hand_made.write_text("---\ntype: concept\n---\n\n## Compiled Truth\nBeta.\n", encoding="utf-8")
    write_page(structure, "alpha")
    same_file_either_way = (structure.concepts_dir / "beta.md").exists()
    llm = ScriptedLLM(reply_for("Beta", '["alpha"]'))

    await make_linter(llm, structure)._discover_connections()

    names = [path.name for path in structure.concepts_dir.glob("*.md")]
    assert sorted(name.lower() for name in names) == ["alpha.md", "beta.md"]
    # Where "Beta.md" and "beta.md" are one file, publishing rewrites the page itself.
    assert ("[[alpha]]" in hand_made.read_text(encoding="utf-8")) is same_file_either_way


@pytest.mark.asyncio
async def test_a_page_that_cannot_be_decoded_is_skipped_and_the_others_still_run(structure: WikiStructure) -> None:
    (structure.concepts_dir / "broken.md").write_bytes(b"\xff\xfe\x00 not utf-8")
    alpha = write_page(structure, "alpha")
    write_page(structure, "beta")
    llm = ScriptedLLM(reply_for("alpha", '["beta"]'))

    count = await make_linter(llm, structure)._discover_connections()

    assert count == 1
    assert sorted(llm.articles()) == ["alpha", "beta"]
    assert "[[beta]]" in alpha.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_a_vault_with_one_page_never_asks_the_model(structure: WikiStructure) -> None:
    write_page(structure, "alpha")
    llm = ScriptedLLM('["alpha"]')

    count = await make_linter(llm, structure)._discover_connections()

    assert count == 0
    assert llm.prompts == []


@pytest.mark.asyncio
@pytest.mark.parametrize("reply", ['[1, null, {"a": 1}, "beta"]', "I cannot tell which pages belong together."])
async def test_a_reply_that_is_not_a_list_of_names_adds_only_the_valid_names(
    structure: WikiStructure, reply: str
) -> None:
    alpha = write_page(structure, "alpha")
    write_page(structure, "beta")
    llm = ScriptedLLM(reply_for("alpha", reply))

    count = await make_linter(llm, structure)._discover_connections()

    assert count == (1 if "beta" in reply else 0)
    assert ("[[beta]]" in alpha.read_text(encoding="utf-8")) is ("beta" in reply)


@pytest.mark.asyncio
async def test_the_excerpt_is_the_article_body_not_its_frontmatter(structure: WikiStructure) -> None:
    filler = "".join(f"note_{index}: FM-ONLY-MARKER filler filler filler\n" for index in range(60))
    write_page(structure, "wide", body="BODY-MARKER-XYZ", extra_front=filler)
    write_page(structure, "beta")
    llm = ScriptedLLM("[]")

    await make_linter(llm, structure)._discover_connections()

    prompt = llm.prompt_for("wide")
    assert "BODY-MARKER-XYZ" in prompt
    assert "FM-ONLY-MARKER" not in prompt


@pytest.mark.asyncio
async def test_an_edit_made_while_the_model_thinks_survives_the_link(structure: WikiStructure) -> None:
    alpha = write_page(structure, "alpha")
    write_page(structure, "beta")
    edited = False

    def _person_edits(prompt: str) -> None:
        nonlocal edited
        if "## Article: alpha\n" in prompt and not edited:
            edited = True
            alpha.write_text(alpha.read_text(encoding="utf-8") + "- 2026-02-02: edit made during the call\n", "utf-8")

    llm = ScriptedLLM(reply_for("alpha", '["beta"]'), on_call=_person_edits)

    count = await make_linter(llm, structure)._discover_connections()

    saved = alpha.read_text(encoding="utf-8")
    assert count == 1
    assert "edit made during the call" in saved
    assert "[[beta]]" in saved


@pytest.mark.asyncio
async def test_a_page_deleted_while_the_model_thinks_is_not_recreated(structure: WikiStructure) -> None:
    alpha = write_page(structure, "alpha")
    write_page(structure, "beta")

    def _person_deletes(prompt: str) -> None:
        if "## Article: alpha\n" in prompt:
            alpha.unlink(missing_ok=True)

    llm = ScriptedLLM(reply_for("alpha", '["beta"]'), on_call=_person_deletes)

    count = await make_linter(llm, structure)._discover_connections()

    assert count == 0
    assert not alpha.exists()
