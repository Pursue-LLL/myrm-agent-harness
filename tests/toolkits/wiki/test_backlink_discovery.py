"""LLM backlink discovery: scope, coverage, input and write safety."""

import re
from collections.abc import Callable
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage, BaseMessage

from myrm_agent_harness.toolkits.wiki import WikiConfig, WikiLinter, WikiStructure
from myrm_agent_harness.toolkits.wiki.core.claims_contract import read_wiki_metadata_file
from myrm_agent_harness.toolkits.wiki.core.related_links import RELATED_HEADING
from myrm_agent_harness.toolkits.wiki.core.section_contract import get_section_inner
from myrm_agent_harness.toolkits.wiki.diagnostics.structural_lint import collect_broken_wikilink_issues
from myrm_agent_harness.toolkits.wiki.pipeline.postprocess import save_metadata
from myrm_agent_harness.toolkits.wiki.pipeline.publication import ArticlePublishOutcome

CURSOR_KEY = "link_discovery_cursor"
_ARTICLE_RE = re.compile(r"^## Article: (.+)$", re.MULTILINE)


class ScriptedLLM:
    """Chat model stand-in: records every prompt, answers from a script, may act mid-call."""

    def __init__(
        self,
        reply: str | Callable[[str], str] = "[]",
        on_call: Callable[[str], None] | None = None,
    ) -> None:
        self.prompts: list[str] = []
        self._reply = reply
        self._on_call = on_call

    async def ainvoke(self, messages: list[BaseMessage]) -> AIMessage:
        prompt = str(messages[-1].content)
        self.prompts.append(prompt)
        if self._on_call is not None:
            self._on_call(prompt)
        reply = self._reply(prompt) if callable(self._reply) else self._reply
        return AIMessage(content=reply)

    def articles(self) -> list[str]:
        return [match for prompt in self.prompts for match in _ARTICLE_RE.findall(prompt)]

    def prompt_for(self, key: str) -> str:
        return next(prompt for prompt in self.prompts if f"## Article: {key}\n" in prompt)


@pytest.fixture
def structure(tmp_path: Path) -> WikiStructure:
    wiki = WikiStructure(tmp_path / "wiki-root")
    wiki.ensure_structure()
    return wiki


def _write_page(
    structure: WikiStructure,
    name: str,
    body: str = "Some facts.",
    *,
    status: str | None = None,
    extra_front: str = "",
    tail: str = "",
) -> Path:
    front = "type: concept\n" + (f"publish_status: {status}\n" if status else "") + extra_front
    path = structure.get_concept_file_path(name)
    path.write_text(
        f"---\n{front}---\n\n## Compiled Truth\n{body}\n\n## Timeline\n- 2026-01-01: created\n{tail}",
        encoding="utf-8",
    )
    return path


def _linter(llm: ScriptedLLM, structure: WikiStructure) -> WikiLinter:
    config = WikiConfig(enable_auto_maintenance=False, enable_backlinks=True)
    return WikiLinter(llm, structure, config)  # type: ignore[arg-type]


def _reply_for(key: str, reply: str) -> Callable[[str], str]:
    return lambda prompt: reply if f"## Article: {key}\n" in prompt else "[]"


@pytest.mark.asyncio
async def test_link_lands_in_the_related_section_not_in_the_last_section(structure: WikiStructure) -> None:
    alpha = _write_page(structure, "alpha", tail="\n## Sources\n- raw/a.md\n")
    _write_page(structure, "beta")
    linter = _linter(ScriptedLLM(_reply_for("alpha", '["beta"]')), structure)

    count = await linter._discover_connections()

    saved = alpha.read_text(encoding="utf-8")
    assert count == 1
    assert "[[beta]]" in (get_section_inner(saved, RELATED_HEADING) or "")
    assert get_section_inner(saved, "## Sources") == "- raw/a.md"


@pytest.mark.asyncio
async def test_related_section_written_by_a_person_keeps_its_text(structure: WikiStructure) -> None:
    alpha = _write_page(structure, "alpha", tail="\n## Related Concepts\n\nMy own reading list.\n\n- [[Old Link]]\n")
    _write_page(structure, "beta")
    linter = _linter(ScriptedLLM(_reply_for("alpha", '["beta"]')), structure)

    await linter._discover_connections()

    inner = get_section_inner(alpha.read_text(encoding="utf-8"), RELATED_HEADING) or ""
    assert "My own reading list." in inner
    assert "[[Old Link]]" in inner
    assert "[[beta]]" in inner


@pytest.mark.asyncio
async def test_same_named_pages_get_a_link_that_names_exactly_one_page(structure: WikiStructure) -> None:
    _write_page(structure, "rust/overview")
    _write_page(structure, "go/overview")
    intro = _write_page(structure, "intro")
    llm = ScriptedLLM(_reply_for("intro", '["overview", "go/overview"]'))

    count = await _linter(llm, structure)._discover_connections()

    saved = intro.read_text(encoding="utf-8")
    assert count == 1
    assert "[[go/overview]]" in saved
    assert "[[overview]]" not in saved
    assert "- overview\n" not in llm.prompt_for("intro")
    assert collect_broken_wikilink_issues(structure) == []


@pytest.mark.asyncio
async def test_a_page_counts_one_link_however_the_model_spells_it(structure: WikiStructure) -> None:
    alpha = _write_page(structure, "alpha")
    _write_page(structure, "beta")
    llm = ScriptedLLM(_reply_for("alpha", '["beta", "Beta", "BETA"]'))

    count = await _linter(llm, structure)._discover_connections()

    assert count == 1
    assert alpha.read_text(encoding="utf-8").lower().count("[[beta]]") == 1


@pytest.mark.asyncio
async def test_a_page_the_article_already_links_is_neither_added_nor_counted(structure: WikiStructure) -> None:
    alpha = _write_page(structure, "alpha", body="See [[Beta]] for details.")
    _write_page(structure, "beta")
    before = alpha.read_text(encoding="utf-8")

    count = await _linter(ScriptedLLM(_reply_for("alpha", '["beta"]')), structure)._discover_connections()

    assert count == 0
    assert alpha.read_text(encoding="utf-8") == before


@pytest.mark.asyncio
async def test_a_link_the_publish_gate_refused_is_not_a_connection(
    structure: WikiStructure, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_page(structure, "alpha")
    _write_page(structure, "beta")
    monkeypatch.setattr(
        "myrm_agent_harness.toolkits.wiki.maintenance.backlink_discovery.publish_concept_article",
        AsyncMock(return_value=ArticlePublishOutcome.BLOCKED),
    )

    count = await _linter(ScriptedLLM(_reply_for("alpha", '["beta"]')), structure)._discover_connections()

    assert count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["draft", "blocked"])
async def test_unpublished_pages_are_neither_rewritten_nor_offered_as_targets(
    structure: WikiStructure, status: str
) -> None:
    live = _write_page(structure, "live")
    held = _write_page(structure, "held", status=status)
    _write_page(structure, "other")
    held_before = held.read_bytes()
    llm = ScriptedLLM('["held", "other"]')

    await _linter(llm, structure)._discover_connections()

    assert held.read_bytes() == held_before
    assert "held" not in llm.articles()
    assert all("- held\n" not in prompt for prompt in llm.prompts)
    saved = live.read_text(encoding="utf-8")
    assert "[[other]]" in saved
    assert "[[held]]" not in saved


@pytest.mark.asyncio
async def test_template_pages_are_out_of_scope(structure: WikiStructure) -> None:
    _write_page(structure, "alpha")
    _write_page(structure, "beta")
    template = structure.templates_dir / "note.md"
    template.write_text("---\ntype: template\n---\n\n## Compiled Truth\n{{body}}\n", encoding="utf-8")
    template_before = template.read_bytes()
    llm = ScriptedLLM("[]")

    await _linter(llm, structure)._discover_connections()

    assert sorted(llm.articles()) == ["alpha", "beta"]
    assert all("note" not in prompt for prompt in llm.prompts)
    assert template.read_bytes() == template_before


@pytest.mark.asyncio
async def test_a_page_publishing_cannot_address_is_linked_to_but_never_rewritten(structure: WikiStructure) -> None:
    hand_made = structure.concepts_dir / "Alpha Notes.md"
    hand_made.write_text("---\ntype: concept\n---\n\n## Compiled Truth\nAlpha.\n", encoding="utf-8")
    beta = _write_page(structure, "beta")
    before = hand_made.read_bytes()
    llm = ScriptedLLM('["Alpha Notes", "beta"]')

    count = await _linter(llm, structure)._discover_connections()

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
    _write_page(local, "alpha")
    _write_page(local, "beta")
    llm = ScriptedLLM(_reply_for("alpha", '["beta", "shared"]'))

    count = await _linter(llm, local)._discover_connections()

    assert count == 1
    assert sorted(llm.articles()) == ["alpha", "beta"]
    assert all("shared" not in prompt for prompt in llm.prompts)


@pytest.mark.asyncio
async def test_every_page_gets_its_turn_across_runs(structure: WikiStructure) -> None:
    keys = [f"page-{index:02d}" for index in range(30)]
    for key in keys:
        _write_page(structure, key)
    llm = ScriptedLLM("[]")
    linter = _linter(llm, structure)

    await linter._discover_connections()
    first = llm.articles()
    cursor = read_wiki_metadata_file(structure.get_wiki_metadata_path())[CURSOR_KEY]
    llm.prompts.clear()
    await linter._discover_connections()
    second = llm.articles()

    assert first == keys[:20]
    assert cursor == "page-19"
    assert second == keys[20:] + keys[:10]
    assert set(first) | set(second) == set(keys)


@pytest.mark.asyncio
async def test_small_vault_runs_everything_and_keeps_no_cursor(structure: WikiStructure) -> None:
    for index in range(5):
        _write_page(structure, f"page-{index}")
    llm = ScriptedLLM("[]")

    await _linter(llm, structure)._discover_connections()

    assert sorted(llm.articles()) == [f"page-{index}" for index in range(5)]
    assert CURSOR_KEY not in read_wiki_metadata_file(structure.get_wiki_metadata_path())


@pytest.mark.asyncio
async def test_cursor_survives_the_next_compile_metadata_save(structure: WikiStructure) -> None:
    for index in range(25):
        _write_page(structure, f"page-{index:02d}")
    await _linter(ScriptedLLM("[]"), structure)._discover_connections()

    await save_metadata(structure, concepts_count=25, articles_count=25)

    metadata = read_wiki_metadata_file(structure.get_wiki_metadata_path())
    assert metadata[CURSOR_KEY] == "page-19"
    assert metadata["total_concepts"] == 25


@pytest.mark.asyncio
async def test_a_model_outage_does_not_use_up_the_rotation(structure: WikiStructure) -> None:
    for index in range(25):
        _write_page(structure, f"page-{index:02d}")

    def _down(_prompt: str) -> None:
        raise RuntimeError("llm unavailable")

    count = await _linter(ScriptedLLM("[]", on_call=_down), structure)._discover_connections()

    assert count == 0
    assert CURSOR_KEY not in read_wiki_metadata_file(structure.get_wiki_metadata_path())


@pytest.mark.asyncio
async def test_pages_that_cannot_take_a_link_do_not_hold_the_rotation(structure: WikiStructure) -> None:
    for index in range(25):
        key = f"page-{index:02d}"
        structure.get_concept_file_path(key).write_text(f"# {key}\nNo frontmatter.\n", encoding="utf-8")
    llm = ScriptedLLM('["page-24"]')

    count = await _linter(llm, structure)._discover_connections()

    assert count == 0
    assert read_wiki_metadata_file(structure.get_wiki_metadata_path())[CURSOR_KEY] == "page-19"


@pytest.mark.asyncio
async def test_a_page_named_only_by_case_never_gains_a_case_variant_sibling(structure: WikiStructure) -> None:
    hand_made = structure.concepts_dir / "Beta.md"
    hand_made.write_text("---\ntype: concept\n---\n\n## Compiled Truth\nBeta.\n", encoding="utf-8")
    _write_page(structure, "alpha")
    same_file_either_way = (structure.concepts_dir / "beta.md").exists()
    llm = ScriptedLLM(_reply_for("Beta", '["alpha"]'))

    await _linter(llm, structure)._discover_connections()

    names = [path.name for path in structure.concepts_dir.glob("*.md")]
    assert sorted(name.lower() for name in names) == ["alpha.md", "beta.md"]
    # Where "Beta.md" and "beta.md" are one file, publishing rewrites the page itself.
    assert ("[[alpha]]" in hand_made.read_text(encoding="utf-8")) is same_file_either_way


@pytest.mark.asyncio
async def test_the_excerpt_is_the_article_body_not_its_frontmatter(structure: WikiStructure) -> None:
    filler = "".join(f"note_{index}: FM-ONLY-MARKER filler filler filler\n" for index in range(60))
    _write_page(structure, "wide", body="BODY-MARKER-XYZ", extra_front=filler)
    _write_page(structure, "beta")
    llm = ScriptedLLM("[]")

    await _linter(llm, structure)._discover_connections()

    prompt = llm.prompt_for("wide")
    assert "BODY-MARKER-XYZ" in prompt
    assert "FM-ONLY-MARKER" not in prompt


@pytest.mark.asyncio
async def test_an_edit_made_while_the_model_thinks_survives_the_link(structure: WikiStructure) -> None:
    alpha = _write_page(structure, "alpha")
    _write_page(structure, "beta")
    edited = False

    def _person_edits(prompt: str) -> None:
        nonlocal edited
        if "## Article: alpha\n" in prompt and not edited:
            edited = True
            alpha.write_text(alpha.read_text(encoding="utf-8") + "- 2026-02-02: edit made during the call\n", "utf-8")

    llm = ScriptedLLM(_reply_for("alpha", '["beta"]'), on_call=_person_edits)

    count = await _linter(llm, structure)._discover_connections()

    saved = alpha.read_text(encoding="utf-8")
    assert count == 1
    assert "edit made during the call" in saved
    assert "[[beta]]" in saved


@pytest.mark.asyncio
async def test_a_page_deleted_while_the_model_thinks_is_not_recreated(structure: WikiStructure) -> None:
    alpha = _write_page(structure, "alpha")
    _write_page(structure, "beta")

    def _person_deletes(prompt: str) -> None:
        if "## Article: alpha\n" in prompt:
            alpha.unlink(missing_ok=True)

    llm = ScriptedLLM(_reply_for("alpha", '["beta"]'), on_call=_person_deletes)

    count = await _linter(llm, structure)._discover_connections()

    assert count == 0
    assert not alpha.exists()
