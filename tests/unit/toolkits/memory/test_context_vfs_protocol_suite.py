"""[POS]: tests/unit/toolkits/memory/test_context_vfs_protocol_suite.py
[INPUT]: Synthetic context:// URIs, memory/skill assets, and exploration queries.
[OUTPUT]: Pytest unit tests verifying dual protocol normalization, 5 namespaces, subtree stats, and mounts.
"""

from pathlib import Path

import pytest

from myrm_agent_harness.toolkits.memory import (
    ALLOWED_TOP_NAMESPACES,
    ContextVFSExploreTools,
    ContextVirtualFileSystem,
    CVFSProtocol,
    CVFSProtocolError,
    VFSNamespaceKind,
    VFSNodeType,
)


@pytest.fixture
def temp_db(tmp_path: Path) -> Path:
    return tmp_path / "test_context_vfs.db"


def test_context_vfs_dual_protocol_and_expanded_namespaces() -> None:
    # 1. Dual protocol normalization
    assert CVFSProtocol.normalize_uri("context://") == "context://"
    assert CVFSProtocol.normalize_uri("context:/skills/tool.md") == "context://skills/tool.md"
    assert CVFSProtocol.normalize_uri("ctx://memories/core.json") == "ctx://memories/core.json"
    assert CVFSProtocol.to_canonical_uri("ctx://memories/core.json") == "context://memories/core.json"

    # 2. Expanded 5 root namespaces
    assert len(ALLOWED_TOP_NAMESPACES) == 5
    for ns in (
        VFSNamespaceKind.MEMORIES,
        VFSNamespaceKind.SKILLS,
        VFSNamespaceKind.RESOURCES,
        VFSNamespaceKind.USER,
        VFSNamespaceKind.ARTIFACTS,
    ):
        assert ns.value in ALLOWED_TOP_NAMESPACES
        CVFSProtocol.validate_namespace(f"context://{ns.value}/test.md")
        CVFSProtocol.validate_namespace(f"ctx://{ns.value}/test.md")

    # 3. Traversal protection on context://
    with pytest.raises(CVFSProtocolError, match="Directory traversal"):
        CVFSProtocol.normalize_uri("context://memories/../../secret")

    # 4. Unknown namespace rejection
    with pytest.raises(CVFSProtocolError, match="Invalid top-level namespace"):
        CVFSProtocol.validate_namespace("context://unauthorized_space/test.md")


def test_context_vfs_memories_and_skills_exploration(temp_db: Path) -> None:
    vfs = ContextVirtualFileSystem(db_path=temp_db)

    # 1. Root namespaces exist for both schemes
    ctx_roots = [n.name for n in vfs.ls("ctx://")]
    context_roots = [n.name for n in vfs.ls("context://")]
    for expected in ("memories", "skills", "resources", "user", "artifacts"):
        assert expected in ctx_roots
        assert expected in context_roots

    # 2. Write to memories under context://
    mem_payload = "User prefers concise architectural designs without unnecessary comments."
    node = vfs.write(
        uri="context://memories/preferences/architecture.md",
        content=mem_payload,
        metadata={"priority": "high", "domain": "engineering"},
    )
    assert node.uri == "context://memories/preferences/architecture.md"
    assert node.node_type == VFSNodeType.FILE

    # 3. Read back via alternate ctx:// scheme seamlessly
    cross_read = vfs.read("ctx://memories/preferences/architecture.md")
    assert cross_read.content == mem_payload

    # 4. Write to skills
    skill_payload = "---\nname: data-analyzer\ndescription: Statistical computations\n---"
    vfs.write("context://skills/analysis/SKILL.md", skill_payload)

    # 5. Tree exploration displays white-box hierarchy
    tree_res = vfs.tree("context://", max_depth=3)
    assert "memories/" in tree_res.rendered_tree
    assert "skills/" in tree_res.rendered_tree
    assert "architecture.md" in tree_res.rendered_tree
    assert "SKILL.md" in tree_res.rendered_tree

    vfs.close()


def test_context_vfs_subtree_statistics_and_tools(temp_db: Path) -> None:
    vfs = ContextVirtualFileSystem(db_path=temp_db)
    tools = ContextVFSExploreTools(vfs=vfs)

    # Populate multiple files under skills
    vfs.write("context://skills/code_review/SKILL.md", "# Review Rules\n1. Strict PEP8")
    vfs.write("context://skills/code_review/prompts.md", "Prompt template for code analysis")

    # Calculate subtree stats
    stats = vfs.stat_subtree("context://skills/code_review")
    assert stats.file_count == 2
    assert stats.directory_count >= 1
    assert stats.total_bytes > 0
    assert stats.total_nodes >= 3

    # Tools facade stat
    tool_stat = tools.ctx_stat("context://skills/code_review")
    assert tool_stat.file_count == 2

    vfs.close()


def test_context_vfs_mount_lifecycle(temp_db: Path) -> None:
    vfs = ContextVirtualFileSystem(db_path=temp_db)

    # Mount external memory source
    mount_info = vfs.mount(
        mount_point="context://memories/cloud_vector_store",
        description="External Qdrant vector memory projection",
        is_read_only=True,
    )
    assert mount_info.mount_point == "context://memories/cloud_vector_store"
    assert mount_info.is_read_only is True

    # Check list_mounts
    mounts = vfs.list_mounts()
    assert len(mounts) == 1
    assert mounts[0].description == "External Qdrant vector memory projection"

    vfs.close()


def test_context_vfs_type_filtered_find(temp_db: Path) -> None:
    vfs = ContextVirtualFileSystem(db_path=temp_db)

    vfs.mkdir("context://artifacts/reports")
    vfs.write("context://artifacts/reports/summary.md", "Executive summary of Q3")

    # Find matching keyword 'report' restricted to FILE
    file_matches = vfs.find("report", prefix_uri="context://artifacts", node_type=VFSNodeType.FILE)
    assert len(file_matches) == 1
    assert file_matches[0].name == "summary.md"

    # Find matching keyword 'report' restricted to DIRECTORY
    dir_matches = vfs.find("report", prefix_uri="context://artifacts", node_type=VFSNodeType.DIRECTORY)
    assert len(dir_matches) == 1
    assert dir_matches[0].name == "reports"

    vfs.close()
