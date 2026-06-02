
import pytest

from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure


@pytest.fixture
def temp_wiki_dir(tmp_path):
    structure = WikiStructure(base_dir=tmp_path)
    structure.ensure_structure()
    return structure

def test_sanitize_path():
    assert WikiStructure._sanitize_path("Work/Project A/Design Doc") == "work/project-a/design-doc"
    assert WikiStructure._sanitize_path("///Empty//Dirs///") == "empty/dirs"
    assert WikiStructure._sanitize_path("Root") == "root"

def test_get_concept_file_path(temp_wiki_dir):
    path = temp_wiki_dir.get_concept_file_path("Work/ProjectA/Design")
    assert path.name == "design.md"
    assert path.parent.name == "projecta"
    assert path.parent.parent.name == "work"
    assert path.parent.exists()  # Should create parents

def test_list_concepts(temp_wiki_dir):
    # Create some nested files
    p1 = temp_wiki_dir.get_concept_file_path("A/B/C")
    p1.write_text("test")
    p2 = temp_wiki_dir.get_concept_file_path("A/D")
    p2.write_text("test")

    concepts = temp_wiki_dir.list_concepts()
    assert len(concepts) == 2
    assert p1 in concepts
    assert p2 in concepts

@pytest.mark.asyncio
async def test_delete_folder_safe(temp_wiki_dir):
    class MockIndexer:
        def __init__(self):
            self.deleted = []
        async def delete(self, name):
            self.deleted.append(name)

    indexer = MockIndexer()

    # Create files
    p1 = temp_wiki_dir.get_concept_file_path("FolderA/File1")
    p1.write_text("test")
    p2 = temp_wiki_dir.get_concept_file_path("FolderA/Sub/File2")
    p2.write_text("test")

    # Delete folder
    deleted_count = await temp_wiki_dir.delete_folder_safe("FolderA", indexer)

    assert deleted_count == 2
    assert "foldera/file1" in indexer.deleted
    assert "foldera/sub/file2" in indexer.deleted
    assert not (temp_wiki_dir.concepts_dir / "foldera").exists()
