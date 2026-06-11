
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


# --- scan_folder tests ---


class TestScanFolder:
    """Tests for WikiStructure.scan_folder with directory filtering."""

    def test_scans_normal_files(self, tmp_path):
        ws = WikiStructure(tmp_path / "wiki")
        src = tmp_path / "source"
        src.mkdir()
        (src / "doc.md").write_text("# Doc")
        (src / "sub").mkdir()
        (src / "sub" / "note.txt").write_text("note")
        (src / "deep" / "nested").mkdir(parents=True)
        (src / "deep" / "nested" / "file.org").write_text("* Org")

        files = ws.scan_folder(src)
        assert len(files) == 3
        names = {f.name for f in files}
        assert names == {"doc.md", "note.txt", "file.org"}

    def test_filters_git_directory(self, tmp_path):
        ws = WikiStructure(tmp_path / "wiki")
        src = tmp_path / "source"
        src.mkdir()
        (src / "real.md").write_text("# Real")
        (src / ".git" / "objects").mkdir(parents=True)
        (src / ".git" / "objects" / "info.txt").write_text("git internal")

        files = ws.scan_folder(src)
        assert len(files) == 1
        assert files[0].name == "real.md"

    def test_filters_node_modules(self, tmp_path):
        ws = WikiStructure(tmp_path / "wiki")
        src = tmp_path / "source"
        src.mkdir()
        (src / "notes.md").write_text("# Notes")
        (src / "node_modules" / "react").mkdir(parents=True)
        (src / "node_modules" / "react" / "README.md").write_text("# React")
        (src / "node_modules" / "lodash").mkdir(parents=True)
        (src / "node_modules" / "lodash" / "README.md").write_text("# Lodash")

        files = ws.scan_folder(src)
        assert len(files) == 1
        assert files[0].name == "notes.md"

    def test_filters_hidden_directories_but_keeps_hidden_files(self, tmp_path):
        ws = WikiStructure(tmp_path / "wiki")
        src = tmp_path / "source"
        src.mkdir()
        (src / ".hidden-note.md").write_text("# Hidden")
        (src / ".obsidian" / "plugins").mkdir(parents=True)
        (src / ".obsidian" / "plugins" / "config.md").write_text("cfg")
        (src / ".venv" / "lib").mkdir(parents=True)
        (src / ".venv" / "lib" / "req.txt").write_text("deps")

        files = ws.scan_folder(src)
        assert len(files) == 1
        assert files[0].name == ".hidden-note.md"

    def test_custom_extensions(self, tmp_path):
        ws = WikiStructure(tmp_path / "wiki")
        src = tmp_path / "source"
        src.mkdir()
        (src / "doc.md").write_text("md")
        (src / "doc.rst").write_text("rst")
        (src / "doc.txt").write_text("txt")

        files = ws.scan_folder(src, [".rst"])
        assert len(files) == 1
        assert files[0].name == "doc.rst"

    def test_nonexistent_directory_raises(self, tmp_path):
        ws = WikiStructure(tmp_path / "wiki")
        with pytest.raises(FileNotFoundError):
            ws.scan_folder(tmp_path / "nonexistent")

    def test_filters_pycache(self, tmp_path):
        ws = WikiStructure(tmp_path / "wiki")
        src = tmp_path / "source"
        src.mkdir()
        (src / "readme.md").write_text("# Readme")
        (src / "__pycache__").mkdir()
        (src / "__pycache__" / "cache.txt").write_text("cached")

        files = ws.scan_folder(src)
        assert len(files) == 1
        assert files[0].name == "readme.md"

    def test_empty_directory(self, tmp_path):
        ws = WikiStructure(tmp_path / "wiki")
        src = tmp_path / "source"
        src.mkdir()

        files = ws.scan_folder(src)
        assert files == []
