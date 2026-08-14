"""Tests for scripts/validate_arch_inventory.py and scripts/md_ref_validator.py."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_repo_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_repo_root))

from scripts.md_ref_validator import (
    _discover_pkg_root,
    _extract_md_refs,
    _is_verifiable_ref,
    _path_exists,
    _progressive_paths,
    _resolve_md_ref,
    _resolve_pkg_root,
    _top_level_module_dirs,
    scan_md_refs,
)
import scripts.validate_arch_inventory as arch_module
from scripts.validate_arch_inventory import (
    DirReport,
    _first_table_cell,
    _format_reports,
    _is_inventory_file_cell,
    _listed_py_in_arch,
    _rel_to_repo,
    main as arch_inventory_main,
    scan_directory,
    scan_tree,
)
_TOP_DIRS = frozenset({"agent", "api", "backends", "core", "distribution", "eval", "infra", "observability", "runtime", "toolkits", "utils"})


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
    """Repo-root scan: table validation stays off, md refs must resolve (incl.
    top-level docs such as ARCHITECTURE.md and FRAMEWORK_DESIGN_PRINCIPLES.md)."""
    import subprocess
    import sys

    script = _repo_root / "scripts" / "validate_arch_inventory.py"
    result = subprocess.run(
        [sys.executable, str(script), "--root", str(_repo_root), "--md-refs"],
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
def test_extract_md_refs_keeps_explicit_paths_and_module_shortcuts(tmp_path: Path) -> None:
    md = tmp_path / "doc.md"
    md.write_text(
        """# Doc

See `./toolkits/errors/classifier.py` and `myrm-agent-server/app/api/curator.py`.
Module shortcut `toolkits/errors/classifier.py` is resolved via top-level dirs.
URL `https://example.com/x.py`, bare `runner.py`, and `/etc/hosts` are skipped.
""",
        encoding="utf-8",
    )
    refs = _extract_md_refs(md, _TOP_DIRS)
    assert [(ref, line) for ref, line, _ in refs] == [
        ("./toolkits/errors/classifier.py", 3),
        ("myrm-agent-server/app/api/curator.py", 3),
        ("toolkits/errors/classifier.py", 4),
    ]


@pytest.mark.architecture
def test_extract_md_refs_drops_noise_without_top_dirs(tmp_path: Path) -> None:
    """Without harness top-level dirs (cross-repo scan), module shortcuts are
    not verifiable and are dropped; only explicit refs survive."""
    md = tmp_path / "doc.md"
    md.write_text(
        """# Doc

Module shortcut `toolkits/errors/classifier.py` is not verifiable here.
Explicit `./local.py` and alias `myrm-agent-server/app/api/curator.py` survive.
""",
        encoding="utf-8",
    )
    refs = _extract_md_refs(md, frozenset())
    assert [(ref, line) for ref, line, _ in refs] == [
        ("./local.py", 4),
        ("myrm-agent-server/app/api/curator.py", 4),
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
    refs = _extract_md_refs(md, _TOP_DIRS)
    # The first-cell `docker/` and bare `sandbox/` are not verifiable; the
    # `../Dockerfile` cell captures the row's first-cell dir as its base, and
    # `toolkits/tasks/` is a harness module shortcut.
    assert refs == [
        ("../Dockerfile", 1, "docker"),
        ("toolkits/tasks/", 2, "app/tasks"),
    ]


@pytest.mark.architecture
def test_extract_md_refs_row_dir_uses_first_cell_only(tmp_path: Path) -> None:
    """A plain-text first cell must not borrow a later cell's backticked dir."""
    md = tmp_path / "doc.md"
    md.write_text(
        """| 容器构建   | `docker/`        | `../Dockerfile` |
| 后台任务层 | `app/tasks/`      | 消费 `toolkits/tasks/` |
""",
        encoding="utf-8",
    )
    refs = _extract_md_refs(md, _TOP_DIRS)
    # First cell is plain text -> no row_dir; explicit relative and module
    # shortcut still verified, but neither borrows a later cell's dir.
    assert refs == [
        ("../Dockerfile", 1, None),
        ("toolkits/tasks/", 2, None),
    ]


@pytest.mark.architecture
def test_progressive_paths_strips_symbol_suffixes() -> None:
    assert _progressive_paths("toolkits/mcp/schema.normalize.canonicalize_schema_for_cache") == [
        "toolkits/mcp/schema.normalize.canonicalize_schema_for_cache",
        "toolkits/mcp/schema.normalize",
        "toolkits/mcp/schema",
    ]
    # Real files with dotted names resolve unchanged (first candidate).
    assert _progressive_paths("toolkits/browser/assets/ad_domains.txt") == [
        "toolkits/browser/assets/ad_domains.txt"
    ]
    assert _progressive_paths("docker/Dockerfile.official") == [
        "docker/Dockerfile.official",
        "docker/Dockerfile",
    ]
    assert _progressive_paths("agent/streaming/broadcast/ToolBroadcastBus") == [
        "agent/streaming/broadcast/ToolBroadcastBus",
        "agent/streaming/broadcast",
    ]
    assert _progressive_paths("path/utils::is_timeout_error") == [
        "path/utils::is_timeout_error",
        "path/utils",
    ]


@pytest.mark.architecture
def test_resolve_md_ref_local_relative_and_cross_repo(tmp_path: Path) -> None:
    harness_root = tmp_path / "myrm-agent-harness"
    harness_pkg = harness_root / "src" / "myrm_agent_harness"
    (harness_root / "docs").mkdir(parents=True)
    (harness_root / "pkg").mkdir()
    (harness_pkg / "agent" / "errors").mkdir(parents=True)
    (harness_pkg / "agent" / "errors" / "classifier.py").write_text("x = 1\n", encoding="utf-8")
    (harness_pkg / "agent" / "streaming" / "broadcast").mkdir(parents=True)
    (harness_pkg / "toolkits" / "mcp" / "schema").mkdir(parents=True)
    (harness_pkg / "toolkits" / "mcp" / "schema" / "__init__.py").write_text("", encoding="utf-8")
    (harness_root / "pkg" / "mod.py").write_text("x = 1\n", encoding="utf-8")
    (harness_root / "docs" / "docker").mkdir()
    (harness_root / "docs" / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
    (harness_root / "docs" / "guide.md").write_text("", encoding="utf-8")

    md = harness_root / "docs" / "guide.md"
    pkg = harness_root / "src" / "myrm_agent_harness"
    assert _path_exists(harness_root / "docs", "./guide.md")
    assert _resolve_md_ref(md, "../pkg/mod.py", None, tmp_path, harness_root, pkg)
    # Module shortcut resolution order: md dir -> package root -> tests mirror.
    assert _resolve_md_ref(md, "agent/errors/classifier.py", None, tmp_path, harness_root, pkg)
    assert not _resolve_md_ref(md, "agent/errors/ghost.py", None, tmp_path, harness_root, pkg)
    # Table row dir acts as a secondary base: `../Dockerfile` under `docs/docker/`.
    assert _resolve_md_ref(md, "../Dockerfile", "docker", tmp_path, harness_root, pkg)
    # Harness shorthand drops the src/myrm_agent_harness package prefix.
    assert _resolve_md_ref(md, "myrm-agent-harness/agent/errors/classifier.py", None,
                           tmp_path, harness_root, pkg)
    assert not _resolve_md_ref(md, "myrm-agent-harness/agent/errors/ghost.py", None,
                               tmp_path, harness_root, pkg)
    # Cross-repo shortcut with a symbol suffix must fall through to the
    # progressive candidate (regression: early return skipped it).
    assert _resolve_md_ref(
        md, "myrm-agent-harness/agent/errors/classifier.py.attr", None,
        tmp_path, harness_root, pkg,
    )
    # Progressive resolution: dotted chain and CamelCase class suffix.
    assert _resolve_md_ref(
        md, "toolkits/mcp/schema.normalize.canonicalize_schema_for_cache", None,
        tmp_path, harness_root, pkg,
    )
    assert _resolve_md_ref(
        md, "agent/streaming/broadcast/ToolBroadcastBus", None, tmp_path, harness_root, pkg,
    )


@pytest.mark.architecture
def test_is_verifiable_ref_scopes_top_dirs() -> None:
    assert _is_verifiable_ref("./x.py", frozenset())
    assert _is_verifiable_ref("../x/y.py", frozenset())
    assert _is_verifiable_ref("myrm-agent-server/app/x.py", frozenset())
    assert not _is_verifiable_ref("app/services/features/x.py", frozenset())
    assert _is_verifiable_ref("toolkits/errors/classifier.py", _TOP_DIRS)
    assert not _is_verifiable_ref("toolkits/errors/classifier.py", frozenset())


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


@pytest.mark.architecture
def test_scan_md_refs_prunes_hidden_dirs(tmp_path: Path) -> None:
    """md refs under pruned dirs (.venv/.git/...) are not scanned."""
    venv_md = tmp_path / ".venv" / "doc.md"
    venv_md.parent.mkdir(parents=True)
    venv_md.write_text("Broken: `./ghost.py`\n", encoding="utf-8")
    assert scan_md_refs(tmp_path, monorepo_root=tmp_path, repo_root=tmp_path) == []


@pytest.mark.architecture
def test_scan_md_refs_skips_whitelisted_docs(tmp_path: Path) -> None:
    """Docs in _MD_REF_SKIP_FILES carry planning semantics (e.g. candidate
    verdict tables); their broken-looking refs must not be reported."""
    pkg = tmp_path / "src" / "myrm_agent_harness" / "eval"
    pkg.mkdir(parents=True)
    (pkg / "_ARCH.md").write_text(
        "| `toolkits/eval/` | Not an agent-callable domain capability |\n",
        encoding="utf-8",
    )
    assert scan_md_refs(tmp_path, monorepo_root=tmp_path, repo_root=tmp_path) == []


@pytest.mark.architecture
def test_discover_pkg_root_detects_repo_layouts(tmp_path: Path) -> None:
    harness = tmp_path / "harness"
    (harness / "src" / "myrm_agent_harness").mkdir(parents=True)
    assert _discover_pkg_root(harness) == harness / "src" / "myrm_agent_harness"
    server = tmp_path / "server"
    (server / "app").mkdir(parents=True)
    assert _discover_pkg_root(server) == server / "app"
    # Frontend src/ is not shortcut-scanned (TS refs carry no extension).
    frontend = tmp_path / "frontend"
    (frontend / "src").mkdir(parents=True)
    assert _discover_pkg_root(frontend) is None
    assert _discover_pkg_root(tmp_path) is None
    # When the scanned root is itself a package root, it is returned as-is.
    app_root = tmp_path / "app"
    app_root.mkdir()
    assert _discover_pkg_root(app_root) == app_root
    harness_pkg = tmp_path / "myrm_agent_harness"
    harness_pkg.mkdir()
    assert _discover_pkg_root(harness_pkg) == harness_pkg


@pytest.mark.architecture
def test_resolve_pkg_root_prefers_harness_pkg(tmp_path: Path) -> None:
    harness = tmp_path / "myrm-agent-harness"
    pkg = harness / "src" / "myrm_agent_harness"
    pkg.mkdir(parents=True)
    # Any subtree of the harness repo resolves to the harness package.
    assert _resolve_pkg_root(pkg / "agent", harness) == pkg
    assert _resolve_pkg_root(harness, harness) == pkg
    # A non-harness repo is auto-detected from its own layout.
    server = tmp_path / "myrm-agent-server"
    (server / "app").mkdir(parents=True)
    assert _resolve_pkg_root(server, harness) == server / "app"


@pytest.mark.architecture
def test_scan_md_refs_resolves_server_shortcuts(tmp_path: Path) -> None:
    """Cross-repo scan: server module shortcuts resolve against app/, comma
    enumerations are dropped, and genuinely missing paths are reported."""
    server = tmp_path / "server"
    (server / "app" / "channels" / "protocols").mkdir(parents=True)
    (server / "app" / "channels" / "protocols" / "inbound_profile.py").write_text(
        "x = 1\n", encoding="utf-8"
    )
    (server / "app" / "services" / "config").mkdir(parents=True)
    (server / "app" / "services" / "config" / "health_monitor.py").write_text(
        "x = 1\n", encoding="utf-8"
    )
    (server / "docs").mkdir()
    (server / "docs" / "guide.md").write_text(
        "`channels/protocols/inbound_profile.py` and `services/config/health_monitor` exist; "
        "`channels/ghost.py` broken; `api/voice,stt,tts` is a comma enum.\n",
        encoding="utf-8",
    )
    reports = scan_md_refs(server, monorepo_root=tmp_path, repo_root=tmp_path)
    assert len(reports) == 1
    assert reports[0].broken_refs == (("channels/ghost.py", 1),)


def test_first_table_cell_requires_closed_cell_pair() -> None:
    """A pipe-only fragment must not be treated as a table row."""
    assert _first_table_cell("|dangling") is None
    assert _first_table_cell("not a table row") is None


def test_top_level_module_dirs_excludes_cache_dirs(tmp_path: Path) -> None:
    """Module-shortcut prefixes never include cache/artifact directories."""
    (tmp_path / "agent").mkdir()
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "plain.py").write_text("x = 1\n", encoding="utf-8")
    dirs = _top_level_module_dirs(tmp_path)
    assert "agent" in dirs
    assert "__pycache__" not in dirs


def test_scan_directory_missing_arch_returns_none(tmp_path: Path) -> None:
    """A directory without _ARCH.md produces no report instead of crashing."""
    (tmp_path / "mod.py").write_text("x = 1\n", encoding="utf-8")
    assert scan_directory(tmp_path) is None


def test_scan_tree_prunes_and_skips_irrelevant_dirs(tmp_path: Path) -> None:
    """Prune dirs and dirs without .py files never yield reports."""
    pruned = tmp_path / "__pycache__"
    pruned.mkdir()
    (pruned / "_ARCH.md").write_text("| File | Purpose |\n| --- | --- |\n", encoding="utf-8")
    (pruned / "cached.py").write_text("x = 1\n", encoding="utf-8")
    empty = tmp_path / "empty"
    empty.mkdir()
    (empty / "_ARCH.md").write_text("| File | Purpose |\n| --- | --- |\n", encoding="utf-8")
    assert scan_tree(tmp_path) == []


def test_rel_to_repo_keeps_path_outside_repo(tmp_path: Path) -> None:
    """Paths outside the repository root stay absolute instead of '../'-walking."""
    outside = tmp_path / "outside" / "x.py"
    assert _rel_to_repo(outside) == outside


def test_format_reports_reports_missing_extra(tmp_path: Path) -> None:
    """Missing/extra .py entries are rendered as FAIL lines."""
    arch = tmp_path / "_ARCH.md"
    report = DirReport(
        directory=tmp_path,
        py_files=("real.py",),
        arch_path=arch,
        listed=("listed_ghost.py",),
        missing_in_arch=("real.py",),
        extra_in_arch=("listed_ghost.py",),
    )
    text = _format_reports([report], root_label="test")
    assert "FAIL" in text
    assert "real.py" in text
    assert "listed_ghost.py" in text


def test_main_missing_root_returns_2(tmp_path: Path) -> None:
    """A nonexistent --root is a usage error (exit 2)."""
    assert arch_inventory_main(["--root", str(tmp_path / "missing")]) == 2


def test_main_tables_outside_src_returns_2(tmp_path: Path) -> None:
    """Table scanning outside src/ (without --md-refs) is rejected."""
    assert arch_inventory_main(["--root", str(tmp_path)]) == 2


def test_main_clean_src_returns_0(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A fully documented src/ subtree passes with exit 0."""
    repo = tmp_path / "repo"
    pkg = repo / "src" / "pkg"
    pkg.mkdir(parents=True)
    (pkg / "_ARCH.md").write_text(
        "| File | Purpose |\n| --- | --- |\n| mod.py | entry |\n", encoding="utf-8"
    )
    (pkg / "mod.py").write_text("x = 1\n", encoding="utf-8")
    monkeypatch.setattr(arch_module, "_REPO_ROOT", repo)
    assert arch_inventory_main(["--root", str(pkg), "--json"]) == 0


def test_main_drifted_src_returns_1(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A .py file missing from _ARCH.md fails with exit 1."""
    repo = tmp_path / "repo"
    pkg = repo / "src" / "pkg"
    pkg.mkdir(parents=True)
    (pkg / "_ARCH.md").write_text(
        "| File | Purpose |\n| --- | --- |\n| mod.py | entry |\n", encoding="utf-8"
    )
    (pkg / "stale.py").write_text("x = 1\n", encoding="utf-8")
    monkeypatch.setattr(arch_module, "_REPO_ROOT", repo)
    assert arch_inventory_main(["--root", str(pkg)]) == 1


def test_format_reports_ok_line(tmp_path: Path) -> None:
    """A clean directory renders an OK line with its py-file count."""
    report = DirReport(
        directory=tmp_path,
        py_files=("real.py",),
        arch_path=tmp_path / "_ARCH.md",
        listed=frozenset({"real.py"}),
        missing_in_arch=(),
        extra_in_arch=(),
    )
    text = _format_reports([report], root_label="test")
    assert "OK" in text
    assert "PASS" in text


def test_main_md_refs_clean_returns_0(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """--md-refs on a repo root with resolvable refs passes."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "guide.md").write_text("`./mod.py` is referenced.\n", encoding="utf-8")
    (repo / "mod.py").write_text("x = 1\n", encoding="utf-8")
    monkeypatch.setattr(arch_module, "_REPO_ROOT", repo)
    assert arch_inventory_main(["--root", str(repo), "--md-refs"]) == 0


def test_main_md_refs_broken_returns_1(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """--md-refs with a dangling path reference fails."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "guide.md").write_text("`./ghost.py` is referenced.\n", encoding="utf-8")
    monkeypatch.setattr(arch_module, "_REPO_ROOT", repo)
    assert arch_inventory_main(["--root", str(repo), "--md-refs"]) == 1


def test_main_json_with_md_refs_returns_0(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """--json combined with --md-refs emits an md_refs payload and passes."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "guide.md").write_text("`./mod.py` is referenced.\n", encoding="utf-8")
    (repo / "mod.py").write_text("x = 1\n", encoding="utf-8")
    monkeypatch.setattr(arch_module, "_REPO_ROOT", repo)
    assert arch_inventory_main(["--root", str(repo), "--md-refs", "--json"]) == 0
