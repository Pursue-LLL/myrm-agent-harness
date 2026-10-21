"""Tests that a rename rewrites exactly the links the resolver points at the moved page."""

from pathlib import Path

import pytest

from myrm_agent_harness.toolkits.wiki.core.link_resolver import WikiLinkResolver
from myrm_agent_harness.toolkits.wiki.core.refactor import LinkRefactorEngine
from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure


def _page(structure: WikiStructure, name: str) -> Path:
    path = structure.get_concept_file_path(name)
    path.write_text("---\ntype: concept\n---\n## Compiled Truth\nBody.\n", encoding="utf-8")
    return path


@pytest.fixture
def structure(tmp_path: Path) -> WikiStructure:
    vault = WikiStructure(tmp_path)
    vault.ensure_structure()
    return vault


class TestRenameParity:
    """The resolver and the rename refactor must read a bare link the same way."""

    @pytest.mark.parametrize(
        ("pages", "source", "renamed"),
        [
            (("a/ownership", "b/guide"), "b/guide", "a/ownership"),
            (("a/ownership", "c/ownership", "b/guide"), "b/guide", "a/ownership"),
            (("a/ownership", "c/ownership", "a/guide"), "a/guide", "a/ownership"),
            (("a/ownership", "c/ownership", "a/guide"), "a/guide", "c/ownership"),
            (("a/ownership", "c/ownership", "d/guide"), "d/guide", "c/ownership"),
        ],
    )
    def test_rename_rewrites_a_bare_link_exactly_when_the_resolver_points_it_at_the_renamed_page(
        self, structure: WikiStructure, pages: tuple[str, ...], source: str, renamed: str
    ) -> None:
        for name in pages:
            _page(structure, name)
        source_path = structure.get_concept_file_path(source)
        source_path.write_text("---\ntype: concept\n---\nSee [[Ownership]].\n", encoding="utf-8")
        points_at_renamed = WikiLinkResolver(structure).resolve("Ownership", source) == renamed

        old_file = structure.get_concept_file_path(renamed)
        LinkRefactorEngine(structure.concepts_dir).refactor_links(old_file, old_file.with_name("moved.md"))

        assert ("[[Ownership]]" not in source_path.read_text(encoding="utf-8")) is points_at_renamed

    @pytest.mark.parametrize(
        "spelling",
        [
            "Borrow Checker",
            "borrow-checker.md",
            "Knowledge/Rust/Borrow Checker",
            "knowledge/rust/borrow-checker#Part|label",
            "wiki/knowledge/rust/borrow-checker",
            "concepts/Knowledge/Rust/Borrow Checker.md",
            "../knowledge/rust/borrow-checker",
        ],
    )
    def test_rename_rewrites_every_spelling_the_resolver_points_at_the_renamed_page(
        self, structure: WikiStructure, spelling: str
    ) -> None:
        """A page without title or aliases is still linked by its spoken name."""
        _page(structure, "knowledge/rust/borrow-checker")
        source_path = _page(structure, "guides/start")
        source_path.write_text(f"---\ntype: concept\n---\nSee [[{spelling}]].\n", encoding="utf-8")
        assert WikiLinkResolver(structure).resolve(spelling, "guides/start") == "knowledge/rust/borrow-checker"

        old_file = structure.get_concept_file_path("knowledge/rust/borrow-checker")
        new_file = old_file.with_name("ownership.md")
        old_file.rename(new_file)
        LinkRefactorEngine(structure.concepts_dir).refactor_links(old_file, new_file)

        text = source_path.read_text(encoding="utf-8")
        assert f"[[{spelling}]]" not in text
        rewritten = text.split("[[", 1)[1].split("]]", 1)[0]
        assert WikiLinkResolver(structure).resolve(rewritten, "guides/start") == "knowledge/rust/ownership"

    @pytest.mark.parametrize(
        "spelling",
        [
            "old-dir/sub/page",
            "Old Dir/Sub/Page",
            "wiki/old-dir/sub/page",
            "concepts/Old-Dir/sub/page.md",
            "../old-dir/sub/page",
        ],
    )
    def test_folder_move_rewrites_every_spelling_to_a_link_that_still_resolves(
        self, structure: WikiStructure, spelling: str
    ) -> None:
        _page(structure, "old-dir/sub/page")
        source_path = _page(structure, "guides/start")
        source_path.write_text(f"---\ntype: concept\n---\nSee [[{spelling}]].\n", encoding="utf-8")
        old_dir = structure.concepts_dir / "old-dir"
        new_dir = structure.concepts_dir / "new-dir"
        old_dir.rename(new_dir)

        LinkRefactorEngine(structure.concepts_dir).refactor_links(old_dir, new_dir)

        text = source_path.read_text(encoding="utf-8")
        assert f"[[{spelling}]]" not in text
        rewritten = text.split("[[", 1)[1].split("]]", 1)[0]
        assert WikiLinkResolver(structure).resolve(rewritten, "guides/start") == "new-dir/sub/page"

    def test_bare_name_shared_by_a_page_spelled_differently_stays_ambiguous(self, structure: WikiStructure) -> None:
        """`Borrow Checker.md` and `borrow-checker.md` answer the same spoken name, so it is not renamed blindly."""
        _page(structure, "a/borrow-checker")
        _page(structure, "b/Borrow Checker")
        source_path = _page(structure, "c/guide")
        source_path.write_text("---\ntype: concept\n---\nSee [[Borrow Checker]].\n", encoding="utf-8")
        assert WikiLinkResolver(structure).resolve("Borrow Checker", "c/guide") is None

        old_file = structure.get_concept_file_path("a/borrow-checker")
        new_file = old_file.with_name("ownership.md")
        old_file.rename(new_file)
        LinkRefactorEngine(structure.concepts_dir).refactor_links(old_file, new_file)

        assert "[[Borrow Checker]]" in source_path.read_text(encoding="utf-8")
