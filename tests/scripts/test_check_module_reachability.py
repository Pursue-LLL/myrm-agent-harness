"""Unit tests for scripts.check_module_reachability (CLI wiring, exit codes, loud degradation)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_repo_root = Path(__file__).resolve().parent.parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

from scripts import check_module_reachability as cli


def _write(root: Path, files: dict[str, str]) -> Path:
    for rel, text in files.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return root


@pytest.fixture
def trees(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    harness = _write(
        tmp_path / "pkg",
        {
            "__init__.py": "",
            "agent/__init__.py": "",
            "agent/engine/__init__.py": "",
            "agent/engine/used.py": "def run() -> None: ...\n",
            "api/consumer.py": "from pkg.agent.engine.used import run\n\nrun()\n",
        },
    )
    server = _write(tmp_path / "server", {"service.py": "VALUE = 1\n"})
    monkeypatch.setattr(cli, "HARNESS_SRC", harness)
    monkeypatch.setattr(cli, "SERVER_SRC", server)
    return harness, server


def test_clean_tree_exits_zero(trees: tuple[Path, Path], capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main([]) == 0
    assert "OK: every unit has a production consumer" in capsys.readouterr().out


def test_dead_unit_exits_one_and_names_it(trees: tuple[Path, Path], capsys: pytest.CaptureFixture[str]) -> None:
    harness, _ = trees
    _write(harness, {"agent/engine/orphan.py": "def lost() -> None: ...\n"})
    assert cli.main([]) == 1
    err = capsys.readouterr().err
    assert "agent/engine/orphan" in err
    assert "no allowlist" in err


def test_json_output_lists_dead_units(trees: tuple[Path, Path], capsys: pytest.CaptureFixture[str]) -> None:
    harness, _ = trees
    _write(harness, {"agent/engine/orphan.py": "def lost() -> None: ...\n"})
    assert cli.main(["--json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert [item["unit"] for item in payload["dead"]] == ["agent/engine/orphan"]
    assert payload["units"] == 2


def test_scan_without_units_fails_instead_of_passing_silently(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "HARNESS_SRC", _write(tmp_path / "pkg", {"api/only.py": "X = 1\n"}))
    monkeypatch.setattr(cli, "SERVER_SRC", _write(tmp_path / "server", {"service.py": "X = 1\n"}))
    assert cli.main([]) == 2
    assert "nothing was scanned" in capsys.readouterr().err


def test_missing_server_tree_is_reported_not_green(
    trees: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "SERVER_SRC", tmp_path / "absent")
    assert cli.main([]) == 0
    assert "NOT EVALUATED" in capsys.readouterr().out


def test_require_server_fails_when_the_server_tree_is_missing(
    trees: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "SERVER_SRC", tmp_path / "absent")
    assert cli.main(["--require-server"]) == 3
    assert "server tree not found" in capsys.readouterr().err


def test_dead_server_unit_does_not_keep_a_harness_unit_alive(
    trees: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    harness, server = trees
    _write(harness, {"agent/engine/ghost.py": "def haunt() -> None: ...\n"})
    _write(server, {"svc/dead.py": "from pkg.agent.engine.ghost import haunt\n\nhaunt()\n"})
    assert cli.main([]) == 1
    assert "agent/engine/ghost" in capsys.readouterr().err


def test_server_mode_audits_server_units_and_honours_root_dirs(
    trees: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    _, server = trees
    _write(
        server,
        {
            "main.py": "from server.svc.live import go\n\ngo()\n",
            "svc/live.py": "def go() -> None: ...\n",
            "svc/orphan.py": "def lost() -> None: ...\n",
            "channels/provider.py": "def load() -> None: ...\n",
            "startup/runner.py": "def run() -> None: ...\n",
        },
    )
    assert cli.main(["--server", "--json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["tree"] == "server"
    assert [item["unit"] for item in payload["dead"]] == ["svc/orphan"]


def test_server_root_option_overrides_the_default_tree(
    trees: tuple[Path, Path], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    other = _write(tmp_path / "other", {"svc/orphan.py": "def lost() -> None: ...\n"})
    assert cli.main(["--server", "--server-root", str(other)]) == 1
    assert "svc/orphan" in capsys.readouterr().err


def test_server_mode_fails_when_the_server_tree_is_missing(
    trees: tuple[Path, Path], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["--server", "--server-root", str(tmp_path / "absent")]) == 3
    assert "server tree not found" in capsys.readouterr().err


def test_server_mode_rejects_incremental(trees: tuple[Path, Path]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["--server", "--incremental"])
    assert exit_info.value.code == 2


def test_incremental_skips_without_harness_changes(
    trees: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    harness, _ = trees
    _write(harness, {"agent/engine/orphan.py": "def lost() -> None: ...\n"})
    monkeypatch.setattr(cli, "harness_sources_changed", lambda: False)
    assert cli.main(["--incremental"]) == 0
    assert "skipped" in capsys.readouterr().out
    monkeypatch.setattr(cli, "harness_sources_changed", lambda: True)
    assert cli.main(["--incremental"]) == 1


def test_project_entry_points_reads_console_scripts(tmp_path: Path) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project.scripts]\ntool = "pkg.agent.engine.cli:main"\n', encoding="utf-8")
    assert cli.project_entry_points(pyproject) == ("pkg.agent.engine.cli:main",)
    assert cli.project_entry_points(tmp_path / "missing.toml") == ()
