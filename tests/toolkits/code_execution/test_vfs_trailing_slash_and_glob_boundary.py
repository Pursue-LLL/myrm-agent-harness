"""Unit tests for VikingFSTrailingSlashDirectoryDelineatorAndGlobBoundaryEnforcer.

Verifies unambiguous directory trailing slash delineation, directory traversal
prevention, recursive depth thresholds, limit truncation, and deterministic
ordering for VFS and sandbox glob operations.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from myrm_agent_harness.toolkits.code_execution.vfs import (
    GlobBoundaryEnforcer,
    GlobBoundaryViolationError,
    GlobSafetyConfig,
    TrailingSlashDelineator,
    VFSPathKind,
)


def test_trailing_slash_delineator_path_normalization() -> None:
    # Test separator normalization and slash collapse
    assert TrailingSlashDelineator.normalize_separators("foo\\bar\\baz") == "foo/bar/baz"
    assert TrailingSlashDelineator.normalize_separators("foo//bar///baz/") == "foo/bar/baz/"
    assert TrailingSlashDelineator.normalize_separators("/var//log///") == "/var/log/"

    # Test explicit directory trailing slash injection
    assert TrailingSlashDelineator.delineate_path("src/components", is_dir=True) == "src/components/"
    assert TrailingSlashDelineator.delineate_path("src/components/", is_dir=True) == "src/components/"
    assert TrailingSlashDelineator.delineate_path("src/main.py/", is_dir=False) == "src/main.py"
    assert TrailingSlashDelineator.delineate_path("src/main.py", is_dir=False) == "src/main.py"

    # Test syntactic checks without disk I/O
    assert TrailingSlashDelineator.is_delineated_dir("src/components/") is True
    assert TrailingSlashDelineator.is_delineated_dir("src/main.py") is False
    assert TrailingSlashDelineator.classify_by_marker("src/components/") == VFSPathKind.DIRECTORY
    assert TrailingSlashDelineator.classify_by_marker("src/main.py") == VFSPathKind.FILE

    # Test stripping delineation for OS calls
    assert TrailingSlashDelineator.strip_delineation("src/components/") == "src/components"
    assert TrailingSlashDelineator.strip_delineation("/") == "/"

    # Test batch delineation
    batch_res = TrailingSlashDelineator.batch_delineate([
        ("app/models", True),
        ("app/main.py", False),
    ])
    assert batch_res == ("app/models/", "app/main.py")


def test_glob_boundary_enforcer_trailing_slash_and_structure(tmp_path: Path) -> None:
    # Build directory structure:
    # root/
    #   src/
    #     utils/
    #       helper.py
    #     index.py
    #   README.md
    src_dir = tmp_path / "src"
    utils_dir = src_dir / "utils"
    utils_dir.mkdir(parents=True)

    (utils_dir / "helper.py").write_text("# helper")
    (src_dir / "index.py").write_text("# index")
    (tmp_path / "README.md").write_text("# readme")

    enforcer = GlobBoundaryEnforcer()
    hits = enforcer.safe_glob(tmp_path, "*")

    # Hits must contain src/ (directory with trailing slash) and README.md (file without)
    dir_hits = [h for h in hits if h.is_directory]
    file_hits = [h for h in hits if not h.is_directory]

    assert len(dir_hits) >= 1
    assert dir_hits[0].path == "src/"
    assert dir_hits[0].has_trailing_slash is True
    assert dir_hits[0].kind == VFSPathKind.DIRECTORY

    assert len(file_hits) >= 1
    readme_hit = next(h for h in file_hits if h.raw_name == "README.md")
    assert readme_hit.path == "README.md"
    assert readme_hit.has_trailing_slash is False
    assert readme_hit.kind == VFSPathKind.FILE

    # Recursive glob: all subdirectories must have trailing slashes
    all_hits = enforcer.safe_glob(tmp_path, "**/*")
    paths = [h.path for h in all_hits]
    assert "src/" in paths
    assert "src/utils/" in paths
    assert "src/utils/helper.py" in paths
    assert "src/index.py" in paths
    assert "README.md" in paths


def test_glob_boundary_enforcer_traversal_violation(tmp_path: Path) -> None:
    enforcer = GlobBoundaryEnforcer()

    # Pattern escaping root must trigger GlobBoundaryViolationError
    with pytest.raises(GlobBoundaryViolationError) as exc_info:
        enforcer.safe_glob(tmp_path, "../../**/*.key")

    assert "breaches root directory boundary" in str(exc_info.value)
    audit = enforcer.last_audit
    assert audit is not None
    assert audit.traversal_violations == 1


def test_glob_boundary_enforcer_depth_limiting(tmp_path: Path) -> None:
    # Create deeply nested structure: d1/d2/d3/d4/file.txt
    deep_dir = tmp_path / "d1" / "d2" / "d3" / "d4"
    deep_dir.mkdir(parents=True)
    (deep_dir / "deep.txt").write_text("deep")

    enforcer = GlobBoundaryEnforcer()
    # Restrict max_depth to 2
    config = GlobSafetyConfig(max_depth=2)
    hits = enforcer.safe_glob(tmp_path, "**/*", config=config)

    paths = [h.path for h in hits]
    assert "d1/" in paths
    assert "d1/d2/" in paths
    # Level 3 and 4 should be truncated
    assert "d1/d2/d3/" not in paths
    assert "d1/d2/d3/d4/deep.txt" not in paths

    audit = enforcer.last_audit
    assert audit is not None
    assert audit.truncated_by_depth is True


def test_glob_boundary_enforcer_max_results_and_hidden(tmp_path: Path) -> None:
    # Create 10 files and 1 hidden file
    for i in range(10):
        (tmp_path / f"item_{i:02d}.txt").write_text(f"content {i}")
    (tmp_path / ".hidden_secret").write_text("secret")

    enforcer = GlobBoundaryEnforcer()
    config = GlobSafetyConfig(max_results=5, ignore_hidden=True)
    hits = enforcer.safe_glob(tmp_path, "*", config=config)

    assert len(hits) == 5
    assert all(not h.raw_name.startswith(".") for h in hits)

    audit = enforcer.last_audit
    assert audit is not None
    assert audit.matched_count == 5
    assert audit.truncated_by_limit is True
