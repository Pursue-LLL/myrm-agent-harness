"""[POS]: tests/unit/toolkits/memory/test_cvfs_suite.py
[INPUT]: Synthetic ctx:// URIs, hierarchical documentation assets, and exploration queries.
[OUTPUT]: Pytest test suite verifying CVFS protocol normalization, store persistence, tree rendering, and tools.
"""

from pathlib import Path

import pytest

from myrm_agent_harness.toolkits.memory.cvfs import (
    ContextVFSExploreTools,
    ContextVirtualFileSystem,
    CVFSProtocol,
    CVFSProtocolError,
    VFSNodeType,
)


@pytest.fixture
def temp_db(tmp_path: Path) -> Path:
    return tmp_path / "test_cvfs.db"


def test_cvfs_protocol_normalization_and_security() -> None:
    # 1. Normalization
    assert CVFSProtocol.normalize_uri("ctx://") == "ctx://"
    assert CVFSProtocol.normalize_uri("ctx:/user/preferences") == "ctx://user/preferences"
    assert CVFSProtocol.normalize_uri("/user/preferences") == "ctx://user/preferences"
    assert CVFSProtocol.normalize_uri("ctx://user/preferences/") == "ctx://user/preferences"

    # 2. Directory traversal attack protection
    with pytest.raises(CVFSProtocolError, match="Directory traversal"):
        CVFSProtocol.normalize_uri("ctx://user/../etc/passwd")

    with pytest.raises(CVFSProtocolError, match="Directory traversal"):
        CVFSProtocol.normalize_uri("ctx://../../root")

    # 3. Namespace validation
    CVFSProtocol.validate_namespace("ctx://resources/repo/readme.md")
    CVFSProtocol.validate_namespace("ctx://user/preferences")
    CVFSProtocol.validate_namespace("ctx://artifacts/session_1/output.json")

    with pytest.raises(CVFSProtocolError, match="Invalid top-level namespace"):
        CVFSProtocol.validate_namespace("ctx://malicious_namespace/file.txt")


def test_cvfs_file_write_and_deterministic_read(temp_db: Path) -> None:
    vfs = ContextVirtualFileSystem(db_path=temp_db)

    # 1. Write file with automatic parent directory creation
    payload = "Rule 1: Always write tests.\nRule 2: Never use Any type."
    node = vfs.write(
        uri="ctx://user/preferences/coding_style.md",
        content=payload,
        metadata={"priority": "high", "topic": "engineering"},
    )
    assert node.uri == "ctx://user/preferences/coding_style.md"
    assert node.node_type == VFSNodeType.FILE
    assert node.size_bytes == len(payload.encode("utf-8"))

    # 2. Read full content
    read_res = vfs.read("ctx://user/preferences/coding_style.md")
    assert read_res.content == payload
    assert read_res.size_bytes == len(payload.encode("utf-8"))
    assert read_res.has_more is False

    # 3. Read with offset and limit
    partial = vfs.read("ctx://user/preferences/coding_style.md", offset=0, limit=10)
    assert partial.content == "Rule 1: Al"
    assert partial.has_more is True

    # 4. Read directory raises error
    with pytest.raises(IsADirectoryError):
        vfs.read("ctx://user/preferences")

    # 5. Read non-existent raises error
    with pytest.raises(FileNotFoundError):
        vfs.read("ctx://user/non_existent.md")

    vfs.close()


def test_cvfs_ls_and_tree_hierarchy_rendering(temp_db: Path) -> None:
    vfs = ContextVirtualFileSystem(db_path=temp_db)

    # Populate assets
    vfs.write("ctx://resources/project_alpha/review_guidelines.md", "# Code Review Guidelines")
    vfs.write("ctx://resources/project_alpha/architecture_adr.md", "# ADR 001: SQLite WAL")
    vfs.write("ctx://user/experiences/db_locking.md", "Avoid holding locks across checkpoints.")

    # 1. Test ls on specific path
    res_items = vfs.ls("ctx://resources/project_alpha")
    names = [it.name for it in res_items]
    assert "review_guidelines.md" in names
    assert "architecture_adr.md" in names

    # 2. Test ls on root shows standard namespaces
    root_items = vfs.ls("ctx://")
    root_names = [it.name for it in root_items]
    assert "resources" in root_names
    assert "user" in root_names
    assert "artifacts" in root_names

    # 3. Test ASCII tree rendering
    tree_res = vfs.tree("ctx://", max_depth=3)
    assert tree_res.total_nodes >= 6
    rendered = tree_res.rendered_tree
    assert "ctx://" in rendered
    assert "resources/" in rendered
    assert "project_alpha/" in rendered
    assert "review_guidelines.md" in rendered
    assert "user/" in rendered

    vfs.close()


def test_cvfs_find_and_delete(temp_db: Path) -> None:
    vfs = ContextVirtualFileSystem(db_path=temp_db)

    vfs.write("ctx://resources/repo/python_guide.md", "Python best practices.")
    vfs.write("ctx://user/experiences/rust_notes.md", "Rust ownership rules.")

    # 1. Search keyword
    matches = vfs.find("practices")
    assert len(matches) == 1
    assert matches[0].name == "python_guide.md"

    # Search keyword in name
    matches_name = vfs.find("rust")
    assert len(matches_name) == 1
    assert matches_name[0].name == "rust_notes.md"

    # 2. Recursive delete
    deleted = vfs.delete("ctx://resources/repo")
    assert deleted is True

    # Sub-file is also gone
    assert len(vfs.ls("ctx://resources/repo")) == 0
    with pytest.raises(FileNotFoundError):
        vfs.read("ctx://resources/repo/python_guide.md")

    vfs.close()


def test_agent_explore_tools_facade(temp_db: Path) -> None:
    vfs = ContextVirtualFileSystem(db_path=temp_db)
    tools = ContextVFSExploreTools(vfs=vfs)

    # 1. ctx_write
    w_node = tools.ctx_write("ctx://user/preferences/editor.md", "Default editor: Vim")
    assert w_node.name == "editor.md"

    # 2. ctx_ls
    ls_res = tools.ctx_ls("ctx://user/preferences")
    assert len(ls_res) == 1
    assert ls_res[0].name == "editor.md"

    # 3. ctx_read
    r_res = tools.ctx_read("ctx://user/preferences/editor.md")
    assert "Vim" in r_res.content

    # 4. ctx_tree
    t_res = tools.ctx_tree("ctx://user")
    assert "editor.md" in t_res.rendered_tree

    # 5. ctx_find
    f_res = tools.ctx_find("Vim")
    assert len(f_res) == 1
    assert f_res[0].name == "editor.md"

    vfs.close()
