"""Selecting the source text an article is written from: the budget, the shares, the lines kept and their numbers."""

from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

import pytest

from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure
from myrm_agent_harness.toolkits.wiki.core.types import ConceptInfo
from myrm_agent_harness.toolkits.wiki.pipeline.article_evidence import build_source_evidence, source_budget_chars

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel


@pytest.fixture
def structure(tmp_path: Path) -> WikiStructure:
    wiki = WikiStructure(tmp_path)
    wiki.ensure_structure()
    return wiki


def _concept(name: str, *sources: str, definition: str = "") -> ConceptInfo:
    return ConceptInfo(name=name, definition=definition, mentions=2, source_files=list(sources))


def _write(structure: WikiStructure, name: str, text: str) -> str:
    (structure.raw_dir / name).write_text(text, encoding="utf-8")
    return f"raw/{name}"


def _text_part(evidence: str) -> str:
    """The lines of a single-source evidence block, without its path header."""
    return evidence.split("\n", 1)[1] if "\n" in evidence else ""


def _filler(count: int, start: int = 1) -> list[str]:
    return [f"routine entry {n}: check the equipment ledger and archive the logs" for n in range(start, start + count)]


@pytest.mark.parametrize(
    ("window", "expected"),
    [(200_000, 12_000), (48_000, 12_000), (8_000, 2_000), (None, 12_000)],
)
def test_the_budget_is_the_configured_cap_unless_the_model_window_is_smaller(window: int | None, expected: int) -> None:
    llm = SimpleNamespace() if window is None else SimpleNamespace(n_ctx=window)

    assert source_budget_chars(cast("BaseChatModel", llm), 12_000) == expected


def test_a_source_that_fits_is_sent_whole_with_its_line_numbers(structure: WikiStructure) -> None:
    ref = _write(structure, "a.md", "# Title\n\nbody 1\nbody 2\n")

    evidence = build_source_evidence(structure, _concept("c", ref), 1_000)

    assert evidence == "### raw/a.md\n1| # Title\n2| \n3| body 1\n4| body 2"


def test_no_sources_means_no_evidence(structure: WikiStructure) -> None:
    assert build_source_evidence(structure, _concept("c"), 1_000) == ""


def test_line_numbers_follow_str_splitlines_like_the_claims_contract(structure: WikiStructure) -> None:
    ref = _write(structure, "odd.md", "first\x0csecond\nthird\u2028fourth\n")
    (structure.raw_dir / "crlf.md").write_bytes(b"one\r\ntwo\r\n")

    odd = build_source_evidence(structure, _concept("c", ref), 1_000)
    crlf = build_source_evidence(structure, _concept("c", "raw/crlf.md"), 1_000)

    assert _text_part(odd).splitlines() == ["1| first", "2| second", "3| third", "4| fourth"]
    assert _text_part(crlf) == "1| one\n2| two"


def test_a_long_document_keeps_its_head_and_the_lines_that_match_the_concept(structure: WikiStructure) -> None:
    lines = [
        *_filler(300),
        "The enterprise tier costs 38800 per seat.",
        "Refunds close after 17 days.",
        *_filler(300, 301),
    ]
    ref = _write(structure, "long.md", "\n".join(lines))

    evidence = build_source_evidence(structure, _concept("Enterprise tier", ref, definition="seat price"), 3_000)

    text = _text_part(evidence)
    assert len(text) <= 3_000
    assert "1| routine entry 1:" in text
    assert "301| The enterprise tier costs 38800 per seat." in text
    assert "302| Refunds close after 17 days." in text
    assert "150| routine entry" not in text


def test_a_document_without_a_matching_line_is_cut_to_its_head(structure: WikiStructure) -> None:
    ref = _write(structure, "plain.md", "\n".join(_filler(400)))

    evidence = build_source_evidence(structure, _concept("Quantum entanglement", ref), 2_000)

    text = _text_part(evidence)
    assert text.startswith("1| routine entry 1:")
    assert len(text) <= 2_000 // 8 + 100
    assert "400|" not in text


def test_a_line_matching_one_term_is_ignored_once_a_line_matches_two(structure: WikiStructure) -> None:
    lines = [
        *_filler(200),
        "alpha is mentioned alone here",
        *_filler(200, 201),
        "alpha and beta appear together",
        *_filler(200, 401),
    ]
    ref = _write(structure, "terms.md", "\n".join(lines))

    evidence = build_source_evidence(structure, _concept("alpha beta", ref), 900)

    text = _text_part(evidence)
    assert "402| alpha and beta appear together" in text
    assert "mentioned alone" not in text


def test_a_single_matching_term_is_enough_when_no_line_matches_two(structure: WikiStructure) -> None:
    lines = [*_filler(200), "alpha is mentioned alone here", *_filler(200, 201)]
    ref = _write(structure, "single.md", "\n".join(lines))

    evidence = build_source_evidence(structure, _concept("alpha beta", ref), 900)

    assert "201| alpha is mentioned alone here" in evidence


def test_the_best_matching_lines_are_kept_first_when_the_budget_cannot_hold_them_all(structure: WikiStructure) -> None:
    lines = [*_filler(100), "alpha beta", *_filler(100, 101), "alpha beta gamma delta", *_filler(100, 201)]
    ref = _write(structure, "ranked.md", "\n".join(lines))

    evidence = build_source_evidence(structure, _concept("alpha beta gamma delta", ref), 700)

    text = _text_part(evidence)
    assert "202| alpha beta gamma delta" in text
    assert "101|" not in text


def test_gaps_between_kept_passages_are_marked(structure: WikiStructure) -> None:
    ref = _write(structure, "gap.md", "\n".join([*_filler(200), "alpha beta marker", *_filler(200, 201)]))

    text = _text_part(build_source_evidence(structure, _concept("alpha beta", ref), 1_500))

    assert "\n...\n" in text


@pytest.mark.parametrize("budget", [700, 1_500, 4_000])
def test_the_kept_text_never_exceeds_the_budget_however_many_gaps_it_has(structure: WikiStructure, budget: int) -> None:
    lines = [f"match {n}: alpha beta" if n % 10 == 0 else f"filler {n}" for n in range(1, 2_001)]
    ref = _write(structure, "dense.md", "\n".join(lines))

    text = _text_part(build_source_evidence(structure, _concept("alpha beta", ref), budget))

    assert 0.7 * budget < len(text) <= budget
    assert text.count("\n...\n") > 3


def test_one_giant_line_is_clipped_so_it_cannot_starve_the_rest(structure: WikiStructure) -> None:
    ref = _write(structure, "mini.md", "head line\n" + "x" * 100_000 + "\ntail line\n")

    text = _text_part(build_source_evidence(structure, _concept("c", ref), 1_000))

    assert len(text) <= 1_000
    assert "1| head line" in text
    assert "2| " + "x" * 200 in text
    assert "x" * 300 not in text


def test_sources_share_the_budget_and_a_small_one_leaves_its_room_to_a_large_one(structure: WikiStructure) -> None:
    small = _write(structure, "small.md", "small fact one\nsmall fact two\n")
    large = _write(structure, "large.md", "\n".join(_filler(500)))
    # Every line of the large source matches both terms, so it keeps as much as its share allows.
    evidence = build_source_evidence(structure, _concept("equipment ledger", large, small), 2_000)

    small_block, large_block = (
        next(block for block in evidence.split("\n\n") if block.startswith(f"### {ref}")) for ref in (small, large)
    )
    assert small_block.endswith("1| small fact one\n2| small fact two")
    assert 1_200 < len(_text_part(large_block)) <= 2_000 - len(_text_part(small_block))


def test_many_sources_each_keep_a_head_inside_the_shared_budget(structure: WikiStructure) -> None:
    refs = [_write(structure, f"s{n}.md", "\n".join([f"doc {n} line {k}" for k in range(200)])) for n in range(10)]

    evidence = build_source_evidence(structure, _concept("c", *refs), 3_000)

    blocks = evidence.split("\n\n")
    assert len(blocks) == 10
    assert all(f"1| doc {n} line 0" in block for n, block in enumerate(blocks))
    assert sum(len(_text_part(block)) for block in blocks) <= 3_000


def test_a_zero_budget_lists_the_paths_only(structure: WikiStructure) -> None:
    ref = _write(structure, "a.md", "text\n")

    assert build_source_evidence(structure, _concept("c", ref), 0) == "### raw/a.md"


def test_a_source_that_cannot_be_read_is_listed_by_its_path_without_being_read(structure: WikiStructure) -> None:
    (structure.raw_dir / "binary.md").write_bytes(b"\xff\xfe\x00\x81 not utf-8")
    (structure.raw_dir / "folder.md").mkdir()
    # ``../outside.md`` names a real file, one directory above the raw directory it is resolved against.
    (structure.base_dir / "outside.md").write_text("secret outside the raw directory", encoding="utf-8")
    refs = ["raw/missing.md", "raw/binary.md", "raw/folder.md", "../outside.md", "/etc/hosts", ""]

    evidence = build_source_evidence(structure, _concept("c", *refs), 1_000)

    assert "secret" not in evidence
    assert "not utf-8" not in evidence
    assert "localhost" not in evidence
    assert "\n1|" not in evidence
    assert {line for line in evidence.splitlines() if line.startswith("### ")} == {f"### {ref}" for ref in refs}


def test_the_same_inputs_give_the_same_evidence_whatever_the_order_of_the_sources(structure: WikiStructure) -> None:
    first = _write(structure, "a.md", "\n".join(_filler(300)))
    second = _write(structure, "b.md", "\n".join(_filler(300, 301)))

    assert build_source_evidence(structure, _concept("c", first, second), 2_000) == build_source_evidence(
        structure, _concept("c", second, first, first), 2_000
    )
