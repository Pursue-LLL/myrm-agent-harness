"""Maintenance progress: the LLM phases report how far they are, and an observer can never break a run."""

from pathlib import Path

import pytest

from myrm_agent_harness.toolkits.wiki import WikiConfig, WikiLinter, WikiStructure
from myrm_agent_harness.toolkits.wiki.core.claims_contract import read_wiki_metadata_file
from myrm_agent_harness.toolkits.wiki.maintenance import MaintainMode
from myrm_agent_harness.toolkits.wiki.maintenance.progress import MaintainPhase, MaintainProgress
from tests.toolkits.wiki.discovery_support import CURSOR_KEY, ScriptedLLM, write_page

_SOURCES = "sources:\n  - raw/a.md\n"


@pytest.fixture
def structure(tmp_path: Path) -> WikiStructure:
    wiki = WikiStructure(tmp_path / "wiki-root")
    wiki.ensure_structure()
    return wiki


def _linter(llm: ScriptedLLM, structure: WikiStructure) -> WikiLinter:
    config = WikiConfig(enable_auto_maintenance=True, enable_backlinks=True)
    return WikiLinter(llm, structure, config)  # type: ignore[arg-type]


class _Recorder:
    def __init__(self) -> None:
        self.events: list[tuple[MaintainPhase, int, int]] = []

    def __call__(self, progress: MaintainProgress) -> None:
        self.events.append((progress.phase, progress.done, progress.total))


@pytest.mark.asyncio
async def test_link_discovery_reports_every_page_of_the_batch(structure: WikiStructure) -> None:
    for index in range(25):
        write_page(structure, f"page-{index:02d}")
    recorder = _Recorder()

    await _linter(ScriptedLLM("[]"), structure)._discover_connections(recorder)

    assert recorder.events == [(MaintainPhase.LINK_DISCOVERY, done, 20) for done in range(21)]


@pytest.mark.asyncio
async def test_link_discovery_with_nothing_to_ask_reports_nothing(structure: WikiStructure) -> None:
    write_page(structure, "only-page")
    recorder = _Recorder()

    await _linter(ScriptedLLM("[]"), structure)._discover_connections(recorder)

    assert recorder.events == []


@pytest.mark.asyncio
async def test_drift_review_reports_every_sampled_page(structure: WikiStructure) -> None:
    for index in range(3):
        write_page(structure, f"page-{index}", extra_front=_SOURCES)
    recorder = _Recorder()

    await _linter(ScriptedLLM("NO_DRIFT"), structure)._check_drift(recorder)

    assert recorder.events == [(MaintainPhase.DRIFT_REVIEW, done, 3) for done in range(4)]


@pytest.mark.asyncio
async def test_a_failing_observer_does_not_break_the_run(structure: WikiStructure) -> None:
    for index in range(25):
        write_page(structure, f"page-{index:02d}")
    llm = ScriptedLLM("[]")

    def _broken(_progress: MaintainProgress) -> None:
        raise RuntimeError("observer exploded")

    count = await _linter(llm, structure)._discover_connections(_broken)

    assert count == 0
    assert len(llm.articles()) == 20
    assert read_wiki_metadata_file(structure.get_wiki_metadata_path())[CURSOR_KEY] == "page-19"


@pytest.mark.asyncio
async def test_full_maintenance_reports_drift_review_then_link_discovery(structure: WikiStructure) -> None:
    for index in range(3):
        write_page(structure, f"page-{index}", extra_front=_SOURCES)
    recorder = _Recorder()

    await _linter(ScriptedLLM("NO_DRIFT"), structure).lint_and_maintain(MaintainMode.FULL, on_progress=recorder)

    phases = [phase for phase, _done, _total in recorder.events]
    assert phases == [MaintainPhase.DRIFT_REVIEW] * 4 + [MaintainPhase.LINK_DISCOVERY] * 4


@pytest.mark.asyncio
async def test_structural_maintenance_reports_nothing(structure: WikiStructure) -> None:
    for index in range(3):
        write_page(structure, f"page-{index}", extra_front=_SOURCES)
    recorder = _Recorder()

    await _linter(ScriptedLLM("NO_DRIFT"), structure).lint_and_maintain(MaintainMode.STRUCTURAL, on_progress=recorder)

    assert recorder.events == []
