"""Tests for wiki link target resolution (core.link_resolver)."""

from pathlib import Path

import pytest

from myrm_agent_harness.toolkits.wiki.core.link_resolver import (
    WikiLinkResolver,
    build_wikilink_title_index,
    concept_index_key,
    normalize_wikilink_target,
    page_lookup_keys,
    wikilink_target_exists,
)
from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure


def _page(structure: WikiStructure, name: str, *, aliases: tuple[str, ...] = (), extra: str = "") -> Path:
    path = structure.get_concept_file_path(name)
    alias_line = f"aliases: [{', '.join(aliases)}]\n" if aliases else ""
    path.write_text(f"---\ntype: concept\n{alias_line}{extra}---\n## Compiled Truth\nBody.\n", encoding="utf-8")
    return path


@pytest.fixture
def structure(tmp_path: Path) -> WikiStructure:
    vault = WikiStructure(tmp_path)
    vault.ensure_structure()
    return vault


def test_normalize_wikilink_target_strips_alias_anchor_and_extension() -> None:
    assert normalize_wikilink_target("Foo/Bar|shown") == "Foo/Bar"
    assert normalize_wikilink_target("Foo#Heading") == "Foo"
    assert normalize_wikilink_target("Foo/Bar.md") == "Foo/Bar"


def test_page_lookup_keys_cover_path_title_aliases_and_canonical_id() -> None:
    markdown = "---\ntitle: Own Ership\naliases: [Borrowing, Moves]\ncanonical_id: knowledge.ownership\n---\nBody"
    keys = page_lookup_keys("knowledge/ownership", markdown)
    assert keys == {"knowledge/ownership", "own ership", "borrowing", "moves", "knowledge.ownership"}


class TestResolve:
    def test_resolves_path_forms_to_the_on_disk_key(self, structure: WikiStructure) -> None:
        _page(structure, "Knowledge/Rust/FiveLayerArchitecture")
        resolver = WikiLinkResolver(structure)

        expected = "knowledge/rust/fivelayerarchitecture"
        assert resolver.resolve("knowledge/rust/fivelayerarchitecture") == expected
        assert resolver.resolve("Knowledge/Rust/FiveLayerArchitecture") == expected
        assert resolver.resolve("Knowledge/Rust/FiveLayerArchitecture.md") == expected
        assert resolver.resolve("Knowledge/Rust/FiveLayerArchitecture#Intro|label") == expected
        assert resolver.resolve("concepts/Knowledge/Rust/FiveLayerArchitecture") == expected

    def test_resolves_unique_alias_title_and_canonical_id(self, structure: WikiStructure) -> None:
        _page(structure, "knowledge/borrow-checker", aliases=("Borrow Checker",), extra="title: The Checker\n")
        resolver = WikiLinkResolver(structure)

        assert resolver.resolve("Borrow Checker") == "knowledge/borrow-checker"
        assert resolver.resolve("borrow checker") == "knowledge/borrow-checker"
        assert resolver.resolve("The Checker") == "knowledge/borrow-checker"

    def test_ambiguous_alias_is_not_resolved(self, structure: WikiStructure) -> None:
        _page(structure, "a/first", aliases=("Shared",))
        _page(structure, "b/second", aliases=("Shared",))
        resolver = WikiLinkResolver(structure)

        assert resolver.resolve("Shared") is None

    @pytest.mark.parametrize("target", ["", "Missing Page", "https://example.com/page", "system:crm"])
    def test_unknown_and_non_concept_targets_return_none(self, structure: WikiStructure, target: str) -> None:
        _page(structure, "known")
        assert WikiLinkResolver(structure).resolve(target) is None

    def test_explicit_relative_target_resolves_against_source_directory(self, structure: WikiStructure) -> None:
        _page(structure, "knowledge/rust/lifetimes")
        resolver = WikiLinkResolver(structure)

        assert resolver.resolve("./lifetimes", source="knowledge/rust/ownership") == "knowledge/rust/lifetimes"
        assert resolver.resolve("../rust/lifetimes", source="knowledge/other/page") == "knowledge/rust/lifetimes"

    def test_unsanitized_on_disk_page_resolves_to_its_real_path(self, structure: WikiStructure) -> None:
        legacy = structure.concepts_dir / "Borrow Checker.md"
        legacy.write_text("---\ntype: concept\n---\nBody", encoding="utf-8")

        assert WikiLinkResolver(structure).resolve("Borrow Checker") == "Borrow Checker"


class TestIncrementalUpdates:
    def test_note_page_makes_new_page_resolvable_and_reports_change(self, structure: WikiStructure) -> None:
        _page(structure, "existing")
        resolver = WikiLinkResolver(structure)
        assert resolver.resolve("Fresh Page") is None

        markdown = "---\ntype: concept\naliases: [Fresh Page]\n---\nBody"
        _page(structure, "fresh/page", aliases=("Fresh Page",))
        assert resolver.note_page("fresh/page", markdown) is True
        assert resolver.resolve("Fresh Page") == "fresh/page"
        assert resolver.note_page("fresh/page", markdown) is False

    def test_note_page_alias_change_replaces_previous_keys(self, structure: WikiStructure) -> None:
        _page(structure, "topic", aliases=("Old Name",))
        resolver = WikiLinkResolver(structure)
        assert resolver.resolve("Old Name") == "topic"

        assert resolver.note_page("topic", "---\ntype: concept\naliases: [New Name]\n---\nBody") is True
        assert resolver.resolve("Old Name") is None
        assert resolver.resolve("New Name") == "topic"

    def test_forget_page_removes_all_keys(self, structure: WikiStructure) -> None:
        _page(structure, "topic", aliases=("Nickname",))
        resolver = WikiLinkResolver(structure)
        assert resolver.resolve("Nickname") == "topic"

        resolver.forget_page("topic")
        assert resolver.resolve("Nickname") is None
        assert resolver.resolve("topic") is None


class TestConceptIndexKey:
    def test_compile_name_maps_to_on_disk_path(self, structure: WikiStructure) -> None:
        _page(structure, "Knowledge/Karpathy/FiveLayerArchitecture")
        assert (
            concept_index_key(structure, "Knowledge/Karpathy/FiveLayerArchitecture")
            == "knowledge/karpathy/fivelayerarchitecture"
        )
        assert concept_index_key(structure, "knowledge/karpathy/fivelayerarchitecture.md") == (
            "knowledge/karpathy/fivelayerarchitecture"
        )

    def test_name_without_backing_page_is_unchanged(self, structure: WikiStructure) -> None:
        assert concept_index_key(structure, "Public Concept") == "Public Concept"
        assert concept_index_key(structure, "") == ""

    def test_unsanitized_on_disk_page_keeps_its_real_path(self, structure: WikiStructure) -> None:
        (structure.concepts_dir / "Borrow Checker.md").write_text("---\ntype: concept\n---\nBody", encoding="utf-8")
        assert concept_index_key(structure, "Borrow Checker") == "Borrow Checker"

    def test_parent_traversal_never_becomes_a_key(self, structure: WikiStructure) -> None:
        outside = structure.concepts_dir.parent / "outside.md"
        outside.write_text("---\ntype: concept\n---\nBody", encoding="utf-8")
        assert (structure.concepts_dir / "../outside.md").is_file()
        assert concept_index_key(structure, "../outside") == "../outside"


class TestLintParity:
    def test_title_index_is_unique_only_and_matches_lint_existence(self, structure: WikiStructure) -> None:
        _page(structure, "a/one", aliases=("Dup", "Solo"))
        _page(structure, "b/two", aliases=("Dup",))
        index = build_wikilink_title_index(structure)

        assert index["solo"] == "a/one"
        assert "dup" not in index
        assert wikilink_target_exists(structure, "Solo", index)
        assert not wikilink_target_exists(structure, "Nope", index)

    def test_title_index_skips_federated_mounts_instead_of_failing(self, tmp_path: Path) -> None:
        public = WikiStructure(tmp_path / "public")
        public.ensure_structure()
        _page(public, "shared/page")
        local = WikiStructure(tmp_path / "local", public_dirs=[tmp_path / "public"])
        local.ensure_structure()
        _page(local, "mine")

        assert build_wikilink_title_index(local) == {"mine": "mine"}
