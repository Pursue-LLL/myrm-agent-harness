"""Tests for scripts/validate_arch_inventory.py."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_repo_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_repo_root))

from scripts.validate_arch_inventory import (
    _extract_md_refs,
    _is_inventory_file_cell,
    _listed_py_in_arch,
    _resolve_md_ref,
    scan_directory,
    scan_md_refs,
)


@pytest.mark.architecture
def test_listed_py_ignores_prose_mentions(tmp_path: Path) -> None:
    arch = tmp_path / "_ARCH.md"
    arch.write_text(
        """# demo/

See server/stream_loop.py and stream_lane_factory.py for wiring.

| File | Role |
|------|------|
| `runner.py` | Core |
| `config.py` | Config |
""",
        encoding="utf-8",
    )
    assert _listed_py_in_arch(arch) == {"runner.py", "config.py"}


@pytest.mark.architecture
def test_listed_py_ignores_multi_file_comparison_cells(tmp_path: Path) -> None:
    arch = tmp_path / "_ARCH.md"
    arch.write_text(
        """| Allowed | Forbidden |
|---------|-----------|
| Root docs and package marker files (see note below) | Vendor packages |
| `_ARCH.md`, `SECURITY_WRAPPER_GUIDE.md`, `__init__.py` | Runtime/cache dirs |
""",
        encoding="utf-8",
    )
    assert _listed_py_in_arch(arch) == set()


@pytest.mark.architecture
def test_is_inventory_file_cell_rejects_prose_lists() -> None:
    assert not _is_inventory_file_cell("_ARCH.md`, `SECURITY_WRAPPER_GUIDE.md`, `__init__.py")
    assert _is_inventory_file_cell("dialog_manager.py")
    assert _is_inventory_file_cell("__init__.py")
    assert not _is_inventory_file_cell("api/hooks.py")


@pytest.mark.architecture
def test_scan_directory_detects_missing_and_extra(tmp_path: Path) -> None:
    (tmp_path / "listed.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "orphan.py").write_text("y = 2\n", encoding="utf-8")
    (tmp_path / "_ARCH.md").write_text(
        """| File | Role |
|------|------|
| `listed.py` | ok |
| `ghost.py` | stale |
""",
        encoding="utf-8",
    )
    report = scan_directory(tmp_path)
    assert report is not None
    assert report.missing_in_arch == ("orphan.py",)
    assert report.extra_in_arch == ("ghost.py",)


@pytest.mark.architecture
def test_middlewares_inventory_passes() -> None:
    middlewares = _repo_root / "src" / "myrm_agent_harness" / "agent" / "middlewares"
    report = scan_directory(middlewares)
    assert report is not None
    assert report.missing_in_arch == ()
    assert report.extra_in_arch == ()


@pytest.mark.architecture
def test_agent_arch_inventory_passes() -> None:
    import subprocess
    import sys

    agent_root = _repo_root / "src" / "myrm_agent_harness" / "agent"
    script = _repo_root / "scripts" / "validate_arch_inventory.py"
    result = subprocess.run(
        [sys.executable, str(script), "--root", str(agent_root)],
        cwd=_repo_root,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr or result.stdout


@pytest.mark.architecture
def test_harness_arch_inventory_passes() -> None:
    import subprocess
    import sys

    harness_root = _repo_root / "src" / "myrm_agent_harness"
    script = _repo_root / "scripts" / "validate_arch_inventory.py"
    result = subprocess.run(
        [sys.executable, str(script), "--root", str(harness_root)],
        cwd=_repo_root,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr or result.stdout


@pytest.mark.architecture
def test_harness_md_refs_pass() -> None:
    import subprocess
    import sys

    harness_root = _repo_root / "src" / "myrm_agent_harness"
    script = _repo_root / "scripts" / "validate_arch_inventory.py"
    result = subprocess.run(
        [sys.executable, str(script), "--root", str(harness_root), "--md-refs"],
        cwd=_repo_root,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr or result.stdout


@pytest.mark.architecture
def test_server_md_refs_pass_in_monorepo() -> None:
    """Cross-repo scan: table validation is skipped, md refs must resolve."""
    import subprocess
    import sys

    script = _repo_root / "scripts" / "validate_arch_inventory.py"
    server_root = _repo_root.parent / "myrm-agent" / "myrm-agent-server"
    if not server_root.is_dir():
        pytest.skip("myrm-agent-server not checked out next to harness")
    result = subprocess.run(
        [sys.executable, str(script), "--root", str(server_root), "--md-refs"],
        cwd=_repo_root,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr or result.stdout


@pytest.mark.architecture
def test_extract_md_refs_keeps_explicit_paths_and_drops_noise(tmp_path: Path) -> None:
    md = tmp_path / "doc.md"
    md.write_text(
        """# Doc

See `./toolkits/errors/classifier.py` and `myrm-agent-server/app/api/curator.py`.
Module shortcut `toolkits/errors/classifier.py` (no ./) is not verified.
URL `https://example.com/x.py`, bare `runner.py`, and `/etc/hosts` are skipped.
""",
        encoding="utf-8",
    )
    refs = _extract_md_refs(md)
    assert [(ref, line) for ref, line, _ in refs] == [
        ("./toolkits/errors/classifier.py", 3),
        ("myrm-agent-server/app/api/curator.py", 3),
    ]


@pytest.mark.architecture
def test_extract_md_refs_captures_table_row_dir(tmp_path: Path) -> None:
    md = tmp_path / "doc.md"
    md.write_text(
        """| `docker/`            | 容器构建     | `../Dockerfile`（PyPI / 预构建 wheel）；`sandbox/` 技能沙箱镜像 |
| `app/tasks/`          | 后台任务层   | 消费 harness `toolkits/tasks/` 队列 |
""",
        encoding="utf-8",
    )
    refs = _extract_md_refs(md)
    # Only `./`/`../` and alias-prefixed refs are verifiable. The first-cell
    # `docker/` and bare `sandbox/` / `toolkits/tasks/` are skipped, while the
    # `../Dockerfile` cell captures the row's first-cell dir as its base.
    assert refs == [("../Dockerfile", 1, "docker")]


@pytest.mark.architecture
def test_resolve_md_ref_local_relative_and_cross_repo(tmp_path: Path) -> None:
    (tmp_path / "docs").mkdir()
    (tmp_path / "pkg").mkdir()
    (tmp_path / "docker").mkdir()
    (tmp_path / "docs" / "guide.md").write_text("", encoding="utf-8")
    (tmp_path / "pkg" / "mod.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")

    # Harness shorthand: monorepo root -> myrm-agent-harness/src/myrm_agent_harness/
    harness_pkg = tmp_path / "myrm-agent-harness" / "src" / "myrm_agent_harness"
    (harness_pkg / "agent" / "errors").mkdir(parents=True)
    (harness_pkg / "agent" / "errors" / "classifier.py").write_text("x = 1\n", encoding="utf-8")

    md = tmp_path / "docs" / "guide.md"
    assert _resolve_md_ref(md, "./guide.md", None, tmp_path, tmp_path, tmp_path)
    assert _resolve_md_ref(md, "../pkg/mod.py", None, tmp_path, tmp_path, tmp_path)
    assert not _resolve_md_ref(md, "./missing/target.py", None, tmp_path, tmp_path, tmp_path)
    # Table row dir acts as a secondary base: `../Dockerfile` under `docker/`.
    assert _resolve_md_ref(md, "../Dockerfile", "docker", tmp_path, tmp_path, tmp_path)
    # Harness shorthand drops the src/myrm_agent_harness package prefix.
    assert _resolve_md_ref(md, "myrm-agent-harness/agent/errors/classifier.py", None,
                           tmp_path, tmp_path, tmp_path)
    assert not _resolve_md_ref(md, "myrm-agent-harness/agent/errors/ghost.py", None,
                               tmp_path, tmp_path, tmp_path)


@pytest.mark.architecture
def test_scan_md_refs_reports_broken_and_skips_standalone_aliases(tmp_path: Path) -> None:
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "real.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "sub" / "doc.md").write_text(
        "Refs: `./real.py` works, `./gone/ghost.py` broken, "
        "`myrm-agent/any/where.py` unverifiable when monorepo absent.\n",
        encoding="utf-8",
    )

    reports = scan_md_refs(tmp_path, monorepo_root=tmp_path, repo_root=tmp_path)
    assert len(reports) == 1
    broken = set(reports[0].broken_refs)
    assert ("./gone/ghost.py", 1) in broken
    # Repo alias whose first segment is missing (standalone harness) is skipped.
    assert not any(ref.startswith("myrm-agent/") for ref, _ in broken)


@pytest.mark.architecture
def test_scan_md_refs_skips_prebuilt_skills(tmp_path: Path) -> None:
    prebuilt = tmp_path / "assets" / "prebuilt_skills" / "frontend-development"
    prebuilt.mkdir(parents=True)
    (prebuilt / "SKILL.md").write_text(
        "Prebuilt utility: `cn()` function at `./lib/utils`\n",
        encoding="utf-8",
    )
    assert scan_md_refs(tmp_path, monorepo_root=tmp_path, repo_root=tmp_path) == []
