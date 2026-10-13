"""Tests for wiki link target resolution (core.link_resolver)."""

from pathlib import Path

import pytest

from myrm_agent_harness.toolkits.wiki.core import link_resolver as link_resolver_module
from myrm_agent_harness.toolkits.wiki.core.link_resolver import (
    PageChange,
    WikiLinkResolver,
    concept_index_key,
    concept_page_exists,
    link_lookup_forms,
    page_link_forms,
    page_lookup_keys,
    scan_concept_pages,
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
        unsanitized = structure.concepts_dir / "Borrow Checker.md"
        unsanitized.write_text("---\ntype: concept\n---\nBody", encoding="utf-8")

        assert WikiLinkResolver(structure).resolve("Borrow Checker") == "Borrow Checker"


class TestFileNameResolution:
    """A bare file name: the page in the linking page's folder, else the only such page, else unresolved."""

    @pytest.mark.parametrize(
        "link", ["Ownership", "ownership", "OWNERSHIP", "Ownership|shown", "Ownership#Intro", "Ownership.md"]
    )
    def test_bare_name_resolves_to_the_only_page_with_that_file_name(self, structure: WikiStructure, link: str) -> None:
        _page(structure, "knowledge/rust/ownership")
        assert WikiLinkResolver(structure).resolve(link) == "knowledge/rust/ownership"

    @pytest.mark.parametrize("link", ["PostgreSQL Auth", "Wiki Concept", "metric_gmv_gross", "dim_platform_channel"])
    def test_names_the_built_in_skills_write_resolve_to_their_sanitized_file(
        self, structure: WikiStructure, link: str
    ) -> None:
        _page(structure, f"topics/{link}")
        expected = f"topics/{WikiStructure._sanitize_path(link)}"

        assert WikiLinkResolver(structure).resolve(link) == expected

    def test_name_shared_by_pages_in_different_folders_is_not_resolved(self, structure: WikiStructure) -> None:
        _page(structure, "rust/ownership")
        _page(structure, "law/ownership")
        resolver = WikiLinkResolver(structure)

        assert resolver.resolve("Ownership") is None
        assert resolver.resolve("Ownership", source="elsewhere/guide") is None

    def test_page_in_the_linking_pages_folder_wins_over_the_same_name_elsewhere(self, structure: WikiStructure) -> None:
        _page(structure, "rust/ownership")
        _page(structure, "law/ownership")
        resolver = WikiLinkResolver(structure)

        assert resolver.resolve("Ownership", source="rust/guide") == "rust/ownership"
        assert resolver.resolve("Ownership", source="law/guide") == "law/ownership"

    def test_a_page_links_its_own_name_to_itself(self, structure: WikiStructure) -> None:
        _page(structure, "rust/ownership")
        assert WikiLinkResolver(structure).resolve("Ownership", source="rust/ownership") == "rust/ownership"

    def test_title_or_alias_naming_one_page_beats_a_file_name(self, structure: WikiStructure) -> None:
        _page(structure, "law/property", extra="title: Ownership\n")
        _page(structure, "rust/ownership")

        assert WikiLinkResolver(structure).resolve("Ownership") == "law/property"

    def test_ambiguous_alias_falls_through_to_a_unique_file_name(self, structure: WikiStructure) -> None:
        _page(structure, "a/first", aliases=("Shared",))
        _page(structure, "b/second", aliases=("Shared",))
        _page(structure, "c/shared")

        assert WikiLinkResolver(structure).resolve("Shared") == "c/shared"

    def test_partial_path_is_not_a_bare_name(self, structure: WikiStructure) -> None:
        _page(structure, "knowledge/rust/ownership")
        assert WikiLinkResolver(structure).resolve("rust/ownership") is None


class TestIncrementalUpdates:
    def test_note_page_makes_new_page_resolvable_and_reports_change(self, structure: WikiStructure) -> None:
        _page(structure, "existing")
        resolver = WikiLinkResolver(structure)
        assert resolver.resolve("Fresh Page") is None

        markdown = "---\ntype: concept\naliases: [Fresh Page]\n---\nBody"
        _page(structure, "fresh/page", aliases=("Fresh Page",))
        assert resolver.note_page("fresh/page", markdown) is not None
        assert resolver.resolve("Fresh Page") == "fresh/page"
        assert resolver.note_page("fresh/page", markdown) is None

    def test_note_page_names_the_spellings_a_new_page_answers_to(self, structure: WikiStructure) -> None:
        _page(structure, "existing")
        resolver = WikiLinkResolver(structure)
        assert resolver.note_page("existing", "---\ntype: concept\n---\nBody") is not None

        markdown = "---\ntype: concept\naliases: [Fresh Page]\n---\nBody"
        _page(structure, "fresh/page", aliases=("Fresh Page",))
        change = resolver.note_page("fresh/page", markdown)

        assert change is not None
        assert not change.full_rescan
        assert change.forms == {"fresh/page", "fresh page", "page"}

    def test_note_page_reports_a_page_already_present_in_the_first_scan(self, structure: WikiStructure) -> None:
        """A fresh resolver has reconciled nothing, even for pages its own scan found."""
        _page(structure, "fresh/page", aliases=("Fresh Page",))
        markdown = "---\ntype: concept\naliases: [Fresh Page]\n---\nBody"
        resolver = WikiLinkResolver(structure)

        first = resolver.note_page("fresh/page", markdown)
        assert first is not None
        assert first.full_rescan
        assert resolver.note_page("fresh/page", markdown) is None
        resolver.forget_page("fresh/page")
        _page(structure, "fresh/page", aliases=("Fresh Page",))
        assert resolver.note_page("fresh/page", markdown) is not None

    def test_note_page_reports_once_after_the_vault_was_rescanned(
        self, structure: WikiStructure, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Pages added behind the resolver's back may resolve stored edges that were left raw."""
        _page(structure, "known")
        markdown = "---\ntype: concept\n---\nBody"
        resolver = WikiLinkResolver(structure)
        assert resolver.note_page("known", markdown) is not None
        assert resolver.note_page("known", markdown) is None

        _page(structure, "added/elsewhere")
        monkeypatch.setattr(link_resolver_module, "_FRESHNESS_RECHECK_SECONDS", 0.0)

        rescanned = resolver.note_page("known", markdown)
        assert rescanned == PageChange(
            forms=page_link_forms("known", page_lookup_keys("known", markdown)), full_rescan=True
        )
        assert resolver.note_page("known", markdown) is None
        assert resolver.resolve("added/elsewhere") == "added/elsewhere"

    def test_note_page_alias_change_replaces_previous_keys(self, structure: WikiStructure) -> None:
        _page(structure, "topic", aliases=("Old Name",))
        resolver = WikiLinkResolver(structure)
        assert resolver.resolve("Old Name") == "topic"

        assert resolver.note_page("topic", "---\ntype: concept\naliases: [New Name]\n---\nBody") is not None
        assert resolver.resolve("Old Name") is None
        assert resolver.resolve("New Name") == "topic"

    def test_forgetting_a_page_drops_its_file_name_and_noting_it_again_restores_it(
        self, structure: WikiStructure
    ) -> None:
        _page(structure, "rust/ownership")
        resolver = WikiLinkResolver(structure)
        assert resolver.resolve("Ownership") == "rust/ownership"

        resolver.forget_page("rust/ownership")
        assert resolver.resolve("Ownership") is None

        assert resolver.note_page("rust/ownership", "---\ntype: concept\n---\nBody") is not None
        assert resolver.resolve("Ownership") == "rust/ownership"

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

    def test_name_the_filesystem_rejects_is_unchanged(self, structure: WikiStructure) -> None:
        too_long = "x" * 300
        assert concept_index_key(structure, too_long) == too_long
        assert concept_page_exists(structure, too_long) is False

    def test_parent_traversal_never_becomes_a_key(self, structure: WikiStructure) -> None:
        outside = structure.concepts_dir.parent / "outside.md"
        outside.write_text("---\ntype: concept\n---\nBody", encoding="utf-8")
        assert (structure.concepts_dir / "../outside.md").is_file()
        assert concept_index_key(structure, "../outside") == "../outside"

    def test_absolute_path_outside_the_vault_never_becomes_a_key(self, structure: WikiStructure) -> None:
        outside = structure.concepts_dir.parent / "outside.md"
        outside.write_text("---\ntype: concept\n---\nBody", encoding="utf-8")
        absolute = outside.with_suffix("").as_posix()

        assert concept_page_exists(structure, absolute) is False
        assert concept_index_key(structure, absolute) == absolute


class TestScanConceptPages:
    def test_skips_federated_mounts_instead_of_failing(self, tmp_path: Path) -> None:
        public = WikiStructure(tmp_path / "public")
        public.ensure_structure()
        _page(public, "shared/page")
        local = WikiStructure(tmp_path / "local", public_dirs=[tmp_path / "public"])
        local.ensure_structure()
        _page(local, "mine")

        assert scan_concept_pages(local) == {"mine": frozenset({"mine"})}


class TestLinkForms:
    def test_target_forms_are_casefolded_and_sanitized_after_normalization(self) -> None:
        assert link_lookup_forms("PostgreSQL Auth#Intro|shown") == ("postgresql auth", "postgresql-auth")
        assert link_lookup_forms("concepts/Knowledge/Rust.md") == ("knowledge/rust", "knowledge/rust")
        assert link_lookup_forms("metric_gmv_gross") == ("metric_gmv_gross", "metric-gmv-gross")

    def test_relative_target_forms_are_anchored_at_the_linking_page(self) -> None:
        assert link_lookup_forms("../Sibling", "a/b/page") == ("a/sibling", "a/sibling")

    @pytest.mark.parametrize("target", ["", "https://example.com/page", "system:crm"])
    def test_non_concept_targets_have_no_forms(self, target: str) -> None:
        assert link_lookup_forms(target) == ("", "")

    def test_page_forms_add_the_casefolded_file_name_to_the_lookup_keys(self) -> None:
        keys = frozenset({"knowledge/rust/ownership", "moves"})
        assert page_link_forms("knowledge/rust/Ownership", keys) == {"knowledge/rust/ownership", "moves", "ownership"}
