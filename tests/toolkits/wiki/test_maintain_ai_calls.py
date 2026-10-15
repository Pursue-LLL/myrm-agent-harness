"""A maintenance run tells a model that answered nothing apart from a model that had nothing to improve."""

import asyncio
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from myrm_agent_harness.toolkits.wiki import WikiConfig, WikiLinter, WikiStructure
from myrm_agent_harness.toolkits.wiki.core.claims_contract import read_wiki_metadata_file
from myrm_agent_harness.toolkits.wiki.maintenance import MaintainMode
from myrm_agent_harness.toolkits.wiki.maintenance.ai_calls import AiCallTally
from tests.toolkits.wiki.discovery_support import CURSOR_KEY, ScriptedLLM, write_page

_SOURCES = "sources:\n  - a.md\n"


@pytest.fixture
def structure(tmp_path: Path) -> WikiStructure:
    wiki = WikiStructure(tmp_path / "wiki-root")
    wiki.ensure_structure()
    return wiki


def _linter(llm: ScriptedLLM, structure: WikiStructure) -> WikiLinter:
    config = WikiConfig(enable_auto_maintenance=True, enable_backlinks=True)
    return WikiLinter(llm, structure, config)  # type: ignore[arg-type]


def _down(_prompt: str) -> str:
    raise RuntimeError("provider down")


def _write_pages(structure: WikiStructure, count: int) -> None:
    (structure.raw_dir / "a.md").write_text("raw fact", encoding="utf-8")
    for index in range(count):
        write_page(structure, f"page-{index:02d}", extra_front=_SOURCES)


@pytest.mark.asyncio
async def test_tally_counts_the_calls_that_raised() -> None:
    tally = AiCallTally()

    assert (await tally.ask(ScriptedLLM("ok"), [HumanMessage(content="q")])) == AIMessage(content="ok")  # type: ignore[arg-type]
    with pytest.raises(RuntimeError):
        await tally.ask(ScriptedLLM(_down), [HumanMessage(content="q")])  # type: ignore[arg-type]

    assert (tally.asked, tally.unanswered, tally.unavailable) == (2, 1, False)


@pytest.mark.asyncio
async def test_tally_without_calls_is_not_unavailable() -> None:
    assert AiCallTally().unavailable is False


@pytest.mark.asyncio
async def test_cancellation_is_not_an_unanswered_call() -> None:
    tally = AiCallTally()

    class _Hanging:
        async def ainvoke(self, _messages: list[HumanMessage]) -> AIMessage:
            await asyncio.sleep(60)
            return AIMessage(content="never")

    task = asyncio.create_task(tally.ask(_Hanging(), [HumanMessage(content="q")]))  # type: ignore[arg-type]
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert (tally.asked, tally.unanswered, tally.unavailable) == (1, 0, False)


@pytest.mark.asyncio
async def test_full_maintenance_reports_a_model_that_answered_nothing(structure: WikiStructure) -> None:
    _write_pages(structure, 3)

    result = await _linter(ScriptedLLM(_down), structure).lint_and_maintain(MaintainMode.FULL)

    assert result.ai_unavailable is True
    assert result.connections_discovered == 0


@pytest.mark.asyncio
async def test_full_maintenance_with_a_working_model_is_available(structure: WikiStructure) -> None:
    _write_pages(structure, 3)

    result = await _linter(ScriptedLLM("NO_DRIFT"), structure).lint_and_maintain(MaintainMode.FULL)

    assert result.ai_unavailable is False


@pytest.mark.asyncio
async def test_a_model_that_answered_some_calls_is_available(structure: WikiStructure) -> None:
    _write_pages(structure, 3)

    def _flaky(prompt: str) -> str:
        if "## Article: page-01\n" in prompt or "Wiki Article (page-01)" in prompt:
            raise RuntimeError("rate limited")
        return "NO_DRIFT" if "Wiki Article" in prompt else "[]"

    result = await _linter(ScriptedLLM(_flaky), structure).lint_and_maintain(MaintainMode.FULL)

    assert result.ai_unavailable is False


@pytest.mark.asyncio
async def test_a_run_that_never_asks_the_model_is_not_unavailable(structure: WikiStructure) -> None:
    write_page(structure, "only-page")
    llm = ScriptedLLM(_down)

    full = await _linter(llm, structure).lint_and_maintain(MaintainMode.FULL)
    structural = await _linter(llm, structure).lint_and_maintain(MaintainMode.STRUCTURAL)

    assert (llm.prompts, full.ai_unavailable, structural.ai_unavailable) == ([], False, False)


@pytest.mark.asyncio
async def test_earlier_unanswered_calls_do_not_hold_back_the_link_discovery_rotation(structure: WikiStructure) -> None:
    _write_pages(structure, 25)
    tally = AiCallTally(asked=30, unanswered=30)

    await _linter(ScriptedLLM("[]"), structure)._discover_connections(ai_calls=tally)

    assert read_wiki_metadata_file(structure.get_wiki_metadata_path())[CURSOR_KEY] == "page-19"
    assert (tally.asked, tally.unanswered) == (50, 30)


@pytest.mark.asyncio
async def test_link_discovery_outage_after_a_good_drift_review_still_holds_the_rotation(
    structure: WikiStructure,
) -> None:
    _write_pages(structure, 25)
    tally = AiCallTally()

    def _discovery_down(prompt: str) -> str:
        if "## Article:" in prompt:
            raise RuntimeError("provider down")
        return "NO_DRIFT"

    linter = _linter(ScriptedLLM(_discovery_down), structure)
    await linter._check_drift(ai_calls=tally)
    await linter._discover_connections(ai_calls=tally)

    assert CURSOR_KEY not in read_wiki_metadata_file(structure.get_wiki_metadata_path())
    assert tally.unavailable is False
