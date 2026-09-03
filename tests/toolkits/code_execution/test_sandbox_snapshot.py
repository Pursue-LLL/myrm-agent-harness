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


def test_is_git_repo_property() -> None:
    snapshot_git = SandboxBootstrapSnapshot(
        working_dir="/test",
        top_level_entries=(),
        total_entries_count=0,
        git_branch="main",
    )
    assert snapshot_git.is_git_repo is True

    snapshot_non_git = SandboxBootstrapSnapshot(
        working_dir="/test",
        top_level_entries=(),
        total_entries_count=0,
        git_branch=None,
    )
    assert snapshot_non_git.is_git_repo is False


def test_run_quick_command_failure_and_timeout() -> None:
    from myrm_agent_harness.toolkits.code_execution.sandbox_snapshot import _run_quick_command
    import subprocess

    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd=["sleep"], timeout=1.0)):
        rc, out = _run_quick_command(["sleep", "10"], timeout=1.0)
        assert rc == -1
        assert out == ""


def test_package_manager_lockfiles_and_fallbacks() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        # Test bun lockfile
        (root / "bun.lockb").write_text("bun")
        with patch("shutil.which", side_effect=lambda bin_name: "/usr/bin/" + bin_name if bin_name in ("bun", "npm") else None):
            snap = generate_sandbox_bootstrap_snapshot(root)
            assert snap.recommended_package_manager == "bun"

    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        # Test yarn lockfile
        (root / "yarn.lock").write_text("yarn")
        with patch("shutil.which", side_effect=lambda bin_name: "/usr/bin/" + bin_name if bin_name in ("yarn", "npm") else None):
            snap = generate_sandbox_bootstrap_snapshot(root)
            assert snap.recommended_package_manager == "yarn"

    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        # Test package-lock.json
        (root / "package-lock.json").write_text("{}")
        with patch("shutil.which", side_effect=lambda bin_name: "/usr/bin/" + bin_name if bin_name in ("npm",) else None):
            snap = generate_sandbox_bootstrap_snapshot(root)
            assert snap.recommended_package_manager == "npm"

    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        # Test pyproject.toml fallback when no lockfile exists
        (root / "pyproject.toml").write_text("[project]")
        with patch("shutil.which", side_effect=lambda bin_name: "/usr/bin/" + bin_name if bin_name in ("uv", "pip") else None):
            snap = generate_sandbox_bootstrap_snapshot(root)
            assert snap.recommended_package_manager == "uv"

    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        # Test Cargo.toml fallback
        (root / "Cargo.toml").write_text("[package]")
        with patch("shutil.which", side_effect=lambda bin_name: "/usr/bin/" + bin_name if bin_name in ("cargo",) else None):
            snap = generate_sandbox_bootstrap_snapshot(root)
            assert snap.recommended_package_manager == "cargo"


def test_scandir_os_error_handling() -> None:
    from myrm_agent_harness.toolkits.code_execution.sandbox_snapshot import _scan_top_level_entries

    with patch("os.scandir", side_effect=PermissionError("Access denied")):
        entries, count = _scan_top_level_entries(Path("/protected"), max_entries=20)
        assert entries == ()
        assert count == 0


def test_non_existent_workspace_directory() -> None:
    snap = generate_sandbox_bootstrap_snapshot(Path("/non_existent_path_xyz_123"))
    assert snap.top_level_entries == ()
    assert snap.total_entries_count == 0
    assert snap.git_branch is None


def test_git_cli_missing_fallback() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        (root / ".git").mkdir()

        with patch("shutil.which", return_value=None):
            snap = generate_sandbox_bootstrap_snapshot(root)
            assert snap.git_branch == "detected (git cli missing)"
            assert snap.git_dirty is None


def test_runtimes_and_version_probing() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)

        def mock_which(bin_name: str) -> str | None:
            if bin_name in ("python3", "node", "bun", "go", "rustc", "java", "git", "curl"):
                return f"/usr/local/bin/{bin_name}"
            return None

        def mock_run_quick(cmd: list[str], timeout: float = 1.0) -> tuple[int, str]:
            if "node" in cmd[0]:
                return 0, "v20.10.0"
            if "bun" in cmd[0]:
                return 0, "1.1.20"
            if "go" in cmd[0]:
                return 0, "go1.22.1"
            if "rustc" in cmd[0]:
                return 0, "rustc 1.78.0 (9b00956e5 2024-05-01)"
            if "python" in cmd[0]:
                return 0, "3.12.3"
            return 0, ""

        with patch("shutil.which", side_effect=mock_which):
            with patch("myrm_agent_harness.toolkits.code_execution.sandbox_snapshot._run_quick_command", side_effect=mock_run_quick):
                snap = generate_sandbox_bootstrap_snapshot(root)
                assert any("Python 3.12.3" in r for r in snap.runtimes)
                assert any("Node.js 20.10.0" in r for r in snap.runtimes)
                assert any("Bun 1.1.20" in r for r in snap.runtimes)
                assert any("Go 1.22.1" in r for r in snap.runtimes)
                assert any("Rust 1.78.0" in r for r in snap.runtimes)
                assert "git" in snap.available_tools
                assert "curl" in snap.available_tools


def test_package_manager_config_fallbacks() -> None:
    # Test package.json fallback without lockfile
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        (root / "package.json").write_text("{}")
        with patch("shutil.which", side_effect=lambda bin_name: "/bin/" + bin_name if bin_name in ("bun", "npm") else None):
            snap = generate_sandbox_bootstrap_snapshot(root)
            assert snap.recommended_package_manager == "bun"

    # Test go.mod and go.sum
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        (root / "go.sum").write_text("// test")
        with patch("shutil.which", side_effect=lambda bin_name: "/bin/" + bin_name if bin_name == "go" else None):
            snap = generate_sandbox_bootstrap_snapshot(root)
            assert snap.recommended_package_manager == "go"

    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        (root / "go.mod").write_text("module demo")
        with patch("shutil.which", side_effect=lambda bin_name: "/bin/" + bin_name if bin_name == "go" else None):
            snap = generate_sandbox_bootstrap_snapshot(root)
            assert snap.recommended_package_manager == "go"

    # Test poetry.lock
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        (root / "poetry.lock").write_text("version = 1")
        with patch("shutil.which", side_effect=lambda bin_name: "/bin/" + bin_name if bin_name in ("poetry", "pip") else None):
            snap = generate_sandbox_bootstrap_snapshot(root)
            assert snap.recommended_package_manager == "poetry"


