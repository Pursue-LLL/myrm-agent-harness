"""Unit tests for Workspace File Access Boundary Guard & Actual Path Link Resolver (Item 38).

[INPUT]
- ActualPathLinkResolver, WorkspaceFileAccessGuard, and WorkspaceBoundaryPolicy.

[OUTPUT]
- Verified test outcomes ensuring symlink escapes, path traversals,
  and unauthorized file actions are blocked, while legitimate workspace files are resolved safely.

[POS]
- Harness core security test suite.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from myrm_agent_harness.core.security.workspace_boundary import (
    ActualPathLinkResolver,
    FileAccessVerdict,
    FileActionType,
    SymlinkEscapeError,
    WorkspaceBoundaryError,
    WorkspaceBoundaryPolicy,
    WorkspaceFileAccessGuard,
)


def test_resolver_legitimate_files_inside_workspace(tmp_path: Path) -> None:
    ws_dir = tmp_path / "workspace"
    ws_dir.mkdir()
    sub_file = ws_dir / "notes.txt"
    sub_file.write_text("hello world", encoding="utf-8")

    policy = WorkspaceBoundaryPolicy(workspace_roots=(str(ws_dir),))
    resolver = ActualPathLinkResolver(policy=policy)

    # 1. Test relative path
    res_rel = resolver.resolve("notes.txt")
    assert res_rel.verdict == FileAccessVerdict.ALLOWED
    assert res_rel.is_inside_workspace is True
    assert res_rel.is_regular_file is True
    assert res_rel.can_launch is True
    assert res_rel.can_read is True
    assert res_rel.resolved_physical_path == str(sub_file.resolve())

    # 2. Test file:// URI with line anchor fragment
    file_uri = f"file://{sub_file.resolve()}#L1-L10"
    res_uri = resolver.resolve(file_uri)
    assert res_uri.verdict == FileAccessVerdict.ALLOWED
    assert res_uri.resolved_physical_path == str(sub_file.resolve())


def test_resolver_symlink_escape_detection(tmp_path: Path) -> None:
    ws_dir = tmp_path / "workspace"
    ws_dir.mkdir()
    outside_dir = tmp_path / "outside_secret"
    outside_dir.mkdir()
    secret_file = outside_dir / "credentials.json"
    secret_file.write_text("super_secret", encoding="utf-8")

    # Create symlink inside workspace pointing outside
    symlink_file = ws_dir / "sneaky_link.json"
    os.symlink(str(secret_file), str(symlink_file))

    policy = WorkspaceBoundaryPolicy(workspace_roots=(str(ws_dir),))
    guard = WorkspaceFileAccessGuard(policy=policy)

    # Resolve symlink
    res = guard.evaluate_access("sneaky_link.json", action=FileActionType.LAUNCH_DEFAULT_APP)
    assert res.verdict == FileAccessVerdict.REFUSED_SYMLINK_ESCAPE
    assert res.can_launch is False
    assert res.can_read is False

    # Assert raises SymlinkEscapeError
    with pytest.raises(SymlinkEscapeError):
        guard.assert_action_permitted("sneaky_link.json", action=FileActionType.LAUNCH_DEFAULT_APP)


def test_resolver_path_traversal_outside_workspace(tmp_path: Path) -> None:
    ws_dir = tmp_path / "workspace"
    ws_dir.mkdir()
    outside_file = tmp_path / "outside.txt"
    outside_file.write_text("external content", encoding="utf-8")

    policy = WorkspaceBoundaryPolicy(workspace_roots=(str(ws_dir),))
    guard = WorkspaceFileAccessGuard(policy=policy)

    res = guard.evaluate_access("../outside.txt", action=FileActionType.READ_CONTENT)
    assert res.verdict == FileAccessVerdict.REFUSED_OUTSIDE_WORKSPACE
    assert res.is_inside_workspace is False
    assert res.can_read is False

    with pytest.raises(WorkspaceBoundaryError):
        guard.assert_action_permitted("../outside.txt", action=FileActionType.READ_CONTENT)


def test_missing_file_and_directory_verdicts(tmp_path: Path) -> None:
    ws_dir = tmp_path / "workspace"
    ws_dir.mkdir()
    sub_dir = ws_dir / "subfolder"
    sub_dir.mkdir()

    policy = WorkspaceBoundaryPolicy(workspace_roots=(str(ws_dir),))
    resolver = ActualPathLinkResolver(policy=policy)

    # Missing file
    res_missing = resolver.resolve("non_existent.py")
    assert res_missing.verdict == FileAccessVerdict.REFUSED_MISSING
    assert res_missing.can_launch is False

    # Directory target
    res_dir = resolver.resolve("subfolder")
    assert res_dir.verdict == FileAccessVerdict.REFUSED_NOT_FILE
    assert res_dir.can_launch is False
    assert res_dir.can_reveal is True  # Folder can be revealed in finder


def test_markdown_link_parsing_and_desktop_sanitization(tmp_path: Path) -> None:
    ws_dir = tmp_path / "workspace"
    ws_dir.mkdir()
    doc_file = ws_dir / "doc.md"
    doc_file.write_text("documentation", encoding="utf-8")

    policy = WorkspaceBoundaryPolicy(workspace_roots=(str(ws_dir),))
    guard = WorkspaceFileAccessGuard(policy=policy)

    md_text = f"Check [doc]({doc_file.resolve()}) and [external](https://google.com) and [missing](./404.txt)"
    parsed = guard.parse_and_resolve_markdown_links(md_text)
    assert len(parsed) == 2  # Ignores https://
    assert parsed[0].verdict == FileAccessVerdict.ALLOWED
    assert parsed[1].verdict == FileAccessVerdict.REFUSED_MISSING

    # Desktop reveal sanitization
    sanitized = guard.sanitize_for_desktop_reveal("doc.md")
    assert sanitized == str(doc_file.resolve())

    # Dangerous path with leading dashes or control chars
    with pytest.raises(WorkspaceBoundaryError):
        guard.sanitize_for_desktop_reveal("nonexistent_path")
