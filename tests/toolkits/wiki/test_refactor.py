import pytest

from myrm_agent_harness.toolkits.wiki.core.refactor import LinkRefactorEngine


@pytest.fixture
def temp_concepts_dir(tmp_path):
    concepts_dir = tmp_path / "concepts"
    concepts_dir.mkdir()
    return concepts_dir


def test_refactor_links_rename_file(temp_concepts_dir):
    # Setup
    old_file = temp_concepts_dir / "old_name.md"
    new_file = temp_concepts_dir / "new_name.md"

    referencing_file = temp_concepts_dir / "ref.md"
    referencing_file.write_text("See [Old](old_name.md) for details.")

    # Run
    engine = LinkRefactorEngine(temp_concepts_dir)
    count = engine.refactor_links(old_file, new_file)

    # Assert
    assert count == 1
    assert referencing_file.read_text() == "See [Old](new_name.md) for details."


def test_refactor_links_move_file_to_folder(temp_concepts_dir):
    # Setup
    old_file = temp_concepts_dir / "file.md"
    folder = temp_concepts_dir / "folder"
    folder.mkdir()
    new_file = folder / "file.md"

    referencing_file = temp_concepts_dir / "ref.md"
    referencing_file.write_text("Link: [File](file.md)")

    # Run
    engine = LinkRefactorEngine(temp_concepts_dir)
    count = engine.refactor_links(old_file, new_file)

    # Assert
    assert count == 1
    assert referencing_file.read_text() == "Link: [File](folder/file.md)"


def test_refactor_links_move_folder(temp_concepts_dir):
    # Setup
    old_folder = temp_concepts_dir / "old_folder"
    old_folder.mkdir()

    new_folder = temp_concepts_dir / "new_folder"

    referencing_file = temp_concepts_dir / "ref.md"
    referencing_file.write_text("Link: [Inside](old_folder/inside.md)")

    # Run
    engine = LinkRefactorEngine(temp_concepts_dir)
    count = engine.refactor_links(old_folder, new_folder)

    # Assert
    assert count == 1
    assert referencing_file.read_text() == "Link: [Inside](new_folder/inside.md)"


def test_refactor_canonical_id_pinning_and_supersedes(temp_concepts_dir):
    from myrm_agent_harness.toolkits.wiki.core.canonical_registry import CANONICAL_ID_KEY, derive_canonical_id
    from myrm_agent_harness.toolkits.wiki.core.frontmatter_contract import load_frontmatter_metadata

    # Case A: File without canonical_id gets its identity pinned to the old slug
    old_file_a = temp_concepts_dir / "drafts" / "alpha.md"
    old_file_a.parent.mkdir(parents=True, exist_ok=True)
    old_file_a.write_text("---\ntitle: Alpha Note\n---\nBody content.")

    new_file_a = temp_concepts_dir / "published" / "alpha_final.md"
    new_file_a.parent.mkdir(parents=True, exist_ok=True)
    old_file_a.rename(new_file_a)

    engine = LinkRefactorEngine(temp_concepts_dir)
    report = engine.refactor_links(old_file_a, new_file_a, preserve_alias=True)

    meta_a, body_a = load_frontmatter_metadata(new_file_a.read_text())
    expected_pinned_id = derive_canonical_id("drafts/alpha")
    assert meta_a.get(CANONICAL_ID_KEY) == expected_pinned_id
    assert "drafts/alpha" in meta_a.get("supersedes", [])
    assert "drafts/alpha" in meta_a.get("aliases", [])
    assert body_a.strip() == "Body content."

    # Case B: File with explicit canonical_id preserves its explicit identity
    old_file_b = temp_concepts_dir / "beta.md"
    old_file_b.write_text("---\ncanonical_id: explicit.beta.custom\n---\nBeta content.")
    new_file_b = temp_concepts_dir / "beta_v2.md"
    old_file_b.rename(new_file_b)

    engine.refactor_links(old_file_b, new_file_b, preserve_alias=True)
    meta_b, _ = load_frontmatter_metadata(new_file_b.read_text())
    assert meta_b.get(CANONICAL_ID_KEY) == "explicit.beta.custom"
    assert "beta" in meta_b.get("supersedes", [])
    assert "beta" in meta_b.get("aliases", [])


def test_refactor_short_wikilink_disambiguation(temp_concepts_dir):
    # Setup two folders both containing overview.md
    tech_dir = temp_concepts_dir / "tech"
    tech_dir.mkdir()
    finance_dir = temp_concepts_dir / "finance"
    finance_dir.mkdir()

    tech_overview = tech_dir / "overview.md"
    tech_overview.write_text("Tech overview content")

    finance_overview = finance_dir / "overview.md"
    finance_overview.write_text("Finance overview content")

    # finance/index.md references [[overview]] which resolves to its sibling finance/overview
    finance_index = finance_dir / "index.md"
    finance_index.write_text("See [[overview]] for financial summary.")

    # tech/guide.md references [[overview]] which resolves to its sibling tech/overview
    tech_guide = tech_dir / "guide.md"
    tech_guide.write_text("Check [[overview]] for tech specs.")

    # external.md references [[tech/overview]] explicitly
    external = temp_concepts_dir / "external.md"
    external.write_text("Reference [[tech/overview]] explicitly.")

    # Move tech/overview.md -> tech/architecture.md
    new_tech = tech_dir / "architecture.md"
    tech_overview.rename(new_tech)

    engine = LinkRefactorEngine(temp_concepts_dir)
    report = engine.refactor_links(tech_overview, new_tech)

    # Assertions
    # 1. finance/index.md must NOT be altered because its [[overview]] binds to finance/overview
    assert finance_index.read_text() == "See [[overview]] for financial summary."

    # 2. tech/guide.md sibling short link was safely updated to architecture
    assert tech_guide.read_text() == "Check [[architecture]] for tech specs."

    # 3. external.md explicit path link was updated to tech/architecture
    assert external.read_text() == "Reference [[tech/architecture]] explicitly."

    # 4. Report verification
    assert report.updated_count == 2
    assert set(report.modified_concept_paths) == {"tech/guide", "external"}


def test_refactor_report_protocols(temp_concepts_dir):
    from myrm_agent_harness.toolkits.wiki.core.refactor import RefactorReport

    # Empty report
    empty_report = RefactorReport(0, ())
    assert bool(empty_report) is False
    assert not empty_report
    assert int(empty_report) == 0
    assert str(empty_report) == "0"
    assert empty_report == 0
    assert empty_report == RefactorReport(0, ())
    assert empty_report != 1
    assert empty_report.modified_concept_paths == ()

    # Positive report from refactor_links
    old_file = temp_concepts_dir / "source.md"
    new_file = temp_concepts_dir / "dest.md"
    old_file.write_text("Source note")
    new_file.write_text("Dest note")

    ref_file = temp_concepts_dir / "ref.md"
    ref_file.write_text("Link: [[source]]")

    engine = LinkRefactorEngine(temp_concepts_dir)
    report = engine.refactor_links(old_file, new_file)

    assert isinstance(report.updated_count, int)
    assert bool(report) is True
    assert report
    assert report == 1
    assert int(report) == 1
    assert str(report) == "1"
    assert report.modified_concept_paths == ("ref",)


def test_refactor_cross_platform_case_stem_conflict(temp_concepts_dir):
    """Ensure stem case-folding conflicts (e.g. Overview vs overview) disable cross-folder short-link guessing."""
    alpha_dir = temp_concepts_dir / "alpha"
    alpha_dir.mkdir()
    beta_dir = temp_concepts_dir / "beta"
    beta_dir.mkdir()

    # Create alpha/Overview.md and beta/overview.md
    alpha_overview = alpha_dir / "Overview.md"
    alpha_overview.write_text("Alpha Overview")

    beta_overview = beta_dir / "overview.md"
    beta_overview.write_text("Beta Overview")

    # Referrers
    # 1. gamma/note.md has an ambiguous short link [[Overview]] or [[overview]]
    gamma_dir = temp_concepts_dir / "gamma"
    gamma_dir.mkdir()
    gamma_note = gamma_dir / "note.md"
    gamma_note.write_text("See [[Overview]] for details.")

    # 2. alpha/sibling.md has sibling link [[Overview]]
    alpha_sibling = alpha_dir / "sibling.md"
    alpha_sibling.write_text("Check [[Overview]].")

    # Rename alpha/Overview.md -> alpha/Architecture.md
    new_alpha_overview = alpha_dir / "Architecture.md"
    alpha_overview.rename(new_alpha_overview)

    engine = LinkRefactorEngine(temp_concepts_dir)
    report = engine.refactor_links(alpha_overview, new_alpha_overview)

    # gamma/note.md must NOT be rewritten because [[Overview]] has stem conflict across folders
    assert gamma_note.read_text() == "See [[Overview]] for details."

    # alpha/sibling.md is in the same directory, so it safely resolves and updates
    assert alpha_sibling.read_text() == "Check [[Architecture]]."
    assert report.updated_count == 1
    assert report.modified_concept_paths == ("alpha/sibling",)


def test_refactor_markdown_links_with_anchors(temp_concepts_dir):
    """Ensure standard markdown links with #fragment anchors are preserved on rename."""
    source_file = temp_concepts_dir / "guide.md"
    source_file.write_text("# Guide\n## Installation\nSteps...")

    target_file = temp_concepts_dir / "setup_guide.md"
    source_file.rename(target_file)

    ref_file = temp_concepts_dir / "readme.md"
    ref_file.write_text(
        "Check [Install Guide](guide.md#installation), see [[guide#Installation]], "
        "and [Internal Anchor](#faq) and [Web](https://example.com#test)."
    )

    engine = LinkRefactorEngine(temp_concepts_dir)
    report = engine.refactor_links(source_file, target_file)

    assert report.updated_count == 1
    assert report.modified_concept_paths == ("readme",)

    updated_text = ref_file.read_text()
    assert "[Install Guide](setup_guide.md#installation)" in updated_text
    assert "[[setup_guide#Installation]]" in updated_text
    assert "[Internal Anchor](#faq)" in updated_text
    assert "[Web](https://example.com#test)" in updated_text


def test_refactor_folder_with_preserve_alias_and_code_blocks(temp_concepts_dir):
    from myrm_agent_harness.toolkits.wiki.core.frontmatter_contract import load_frontmatter_metadata

    old_dir = temp_concepts_dir / "old_docs"
    old_dir.mkdir()
    page = old_dir / "page.md"
    page.write_text("---\ntitle: Doc Page\n---\nHello Doc")

    new_dir = temp_concepts_dir / "new_docs"
    old_dir.rename(new_dir)

    ref = temp_concepts_dir / "reference.md"
    ref.write_text(
        "Wiki: [[old_docs/page|Doc Title]], "
        "Code: ```\n[[old_docs/page]]\n``` and `[[old_docs/page]]` inline."
    )

    engine = LinkRefactorEngine(temp_concepts_dir)
    report = engine.refactor_links(old_dir, new_dir, preserve_alias=True)

    assert report.updated_count == 1
    # Check that code block was protected, but link was updated
    text = ref.read_text()
    assert "[[new_docs/page|Doc Title]]" in text
    assert "```\n[[old_docs/page]]\n```" in text
    assert "`[[old_docs/page]]`" in text

    # Check that moved sub-page received alias
    moved_page = new_dir / "page.md"
    meta, _ = load_frontmatter_metadata(moved_page.read_text())
    assert "old_docs/page" in meta.get("aliases", [])


def test_refactor_metadata_existing_aliases_and_scalar_supersedes(temp_concepts_dir):
    from myrm_agent_harness.toolkits.wiki.core.canonical_registry import CANONICAL_ID_KEY
    from myrm_agent_harness.toolkits.wiki.core.frontmatter_contract import load_frontmatter_metadata

    # 1. Existing file with scalar supersedes and list aliases
    old_file = temp_concepts_dir / "item_old.md"
    old_file.write_text(
        "---\n"
        "title: Item\n"
        "supersedes: legacy_v0\n"
        "aliases:\n"
        "  - alias_one\n"
        "---\n"
        "Item content"
    )

    new_file = temp_concepts_dir / "item_new.md"
    old_file.rename(new_file)

    engine = LinkRefactorEngine(temp_concepts_dir)
    engine.refactor_links(old_file, new_file, preserve_alias=True)

    meta, _ = load_frontmatter_metadata(new_file.read_text())
    assert "legacy_v0" in meta.get("supersedes", [])
    assert "item_old" in meta.get("supersedes", [])
    assert "alias_one" in meta.get("aliases", [])
    assert "item_old" in meta.get("aliases", [])

    # 2. File with NO frontmatter at all gets fresh frontmatter injected
    raw_file = temp_concepts_dir / "raw_old.md"
    raw_file.write_text("No frontmatter markdown here.")
    new_raw = temp_concepts_dir / "raw_new.md"
    raw_file.rename(new_raw)

    engine.refactor_links(raw_file, new_raw, preserve_alias=True)
    raw_meta, raw_body = load_frontmatter_metadata(new_raw.read_text())
    assert CANONICAL_ID_KEY in raw_meta
    assert "raw_old" in raw_meta.get("aliases", [])
    assert "No frontmatter markdown here." in raw_body


def test_refactor_cross_directory_short_wikilink_and_folder_wikilink(temp_concepts_dir):
    # 1. Test short link [[target]] updated to [[folder/target]] when moved to subfolder
    sub_dir = temp_concepts_dir / "modules"
    sub_dir.mkdir()
    target = temp_concepts_dir / "unique_note.md"
    target.write_text("Unique content")
    moved_target = sub_dir / "unique_note.md"
    target.rename(moved_target)

    # External file has short link [[unique_note]]
    ext = temp_concepts_dir / "external.md"
    ext.write_text("Link: [[unique_note]]")

    engine = LinkRefactorEngine(temp_concepts_dir)
    engine.refactor_links(target, moved_target)
    assert ext.read_text() == "Link: [[modules/unique_note]]"

    # 2. Test directory-level wikilink [[old_pack]] -> [[new_pack]]
    pack_old = temp_concepts_dir / "old_pack"
    pack_old.mkdir()
    (pack_old / "item.md").write_text("item")
    pack_new = temp_concepts_dir / "new_pack"
    pack_old.rename(pack_new)

    pack_ref = temp_concepts_dir / "pack_ref.md"
    pack_ref.write_text("See [[old_pack]] and [[old_pack/item]].")

    engine.refactor_links(pack_old, pack_new)
    assert pack_ref.read_text() == "See [[new_pack]] and [[new_pack/item]]."






