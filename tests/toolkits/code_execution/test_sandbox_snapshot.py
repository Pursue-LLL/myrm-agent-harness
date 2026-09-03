"""Unit tests for SandboxBootstrapSnapshot generator and formatter.

Tests:
- Empty workspace handling
- Normal directory structure scanning (file/dir distinction)
- Ignored directory filtering (.git, node_modules, etc.)
- Recommended package manager inference from lockfiles
- Git state detection
- XML formatting output and safety
- Large workspace truncation limit protection
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from myrm_agent_harness.toolkits.code_execution.sandbox_snapshot import (
    SandboxBootstrapSnapshot,
    format_bootstrap_snapshot_xml,
    generate_sandbox_bootstrap_snapshot,
)


def test_empty_workspace() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        snapshot = generate_sandbox_bootstrap_snapshot(tmpdir)
        assert snapshot.working_dir == str(Path(tmpdir).resolve())
        assert snapshot.top_level_entries == ()
        assert snapshot.total_entries_count == 0
        xml = format_bootstrap_snapshot_xml(snapshot)
        assert "<sandbox_environment_snapshot>" in xml
        assert "Workspace Contents: [empty directory]" in xml


def test_directory_scanning_and_ignored_filtering() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        # Create regular files and dirs
        (root / "src").mkdir()
        (root / "tests").mkdir()
        (root / "README.md").write_text("# Test Repo")
        (root / "pyproject.toml").write_text("[project]\nname='demo'")

        # Create ignored dirs
        (root / ".git").mkdir()
        (root / "node_modules").mkdir()
        (root / "__pycache__").mkdir()

        snapshot = generate_sandbox_bootstrap_snapshot(root)

        # Ignored dirs must not appear in top_level_entries
        for ignored in (".git", "node_modules", "__pycache__"):
            assert f"{ignored}/" not in snapshot.top_level_entries
            assert ignored not in snapshot.top_level_entries

        # Directories have trailing slash
        assert "src/" in snapshot.top_level_entries
        assert "tests/" in snapshot.top_level_entries
        assert "README.md" in snapshot.top_level_entries
        assert "pyproject.toml" in snapshot.top_level_entries
        assert snapshot.total_entries_count == 4


def test_recommended_package_manager_inference() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        (root / "pnpm-lock.yaml").write_text("lockfileVersion: 5.4")

        with patch("shutil.which", side_effect=lambda bin_name: "/usr/bin/" + bin_name if bin_name in ("pnpm", "npm", "uv") else None):
            snapshot = generate_sandbox_bootstrap_snapshot(root)
            assert "pnpm" in snapshot.package_managers
            assert snapshot.recommended_package_manager == "pnpm"

            xml = format_bootstrap_snapshot_xml(snapshot)
            assert "pnpm (recommended for this project)" in xml


def test_uv_lock_recommendation() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        (root / "uv.lock").write_text("version = 1")

        with patch("shutil.which", side_effect=lambda bin_name: "/usr/bin/" + bin_name if bin_name in ("uv", "pip") else None):
            snapshot = generate_sandbox_bootstrap_snapshot(root)
            assert "uv" in snapshot.package_managers
            assert snapshot.recommended_package_manager == "uv"


def test_max_entries_truncation() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        for i in range(35):
            (root / f"file_{i:02d}.txt").write_text("content")

        snapshot = generate_sandbox_bootstrap_snapshot(root, max_entries=10)
        assert len(snapshot.top_level_entries) == 10
        assert snapshot.total_entries_count == 35

        xml = format_bootstrap_snapshot_xml(snapshot)
        assert "(+25 more)" in xml


def test_git_branch_probing() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        (root / ".git").mkdir()

        def _custom_quick_command(cmd: list[str], timeout: float = 1.0) -> tuple[int, str]:
            if "rev-parse" in cmd:
                return 0, "feature/sandbox-eval"
            if "status" in cmd:
                return 0, "M test.py"
            return 0, "3.12.0"

        with patch("myrm_agent_harness.toolkits.code_execution.sandbox_snapshot._run_quick_command", side_effect=_custom_quick_command):
            snapshot = generate_sandbox_bootstrap_snapshot(root)
            assert snapshot.git_branch == "feature/sandbox-eval"
            assert snapshot.git_dirty is True

            xml = format_bootstrap_snapshot_xml(snapshot)
            assert "Git: feature/sandbox-eval, dirty" in xml
