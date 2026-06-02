
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
