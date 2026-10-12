"""Unit tests for scripts.check_import_resolvability (CLI wiring, exit codes, incremental scope)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_repo_root = Path(__file__).resolve().parent.parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

from scripts import check_import_resolvability as cli


def _write(root: Path, files: dict[str, str]) -> Path:
    for rel, text in files.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return root


@pytest.fixture
def harness(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = _write(
        tmp_path / "pkg",
        {"__init__.py": "", "defs.py": "class A: ...\n", "user.py": "from pkg.defs import A\n"},
    )
    monkeypatch.setattr(cli, "HARNESS_SRC", root)
    monkeypatch.setattr(cli, "_PACKAGE", "pkg")
    return root


def test_clean_tree_exits_zero(harness: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main([]) == 0

    out = capsys.readouterr().out
    assert "OK: every first-party import resolves." in out
    assert "3 files, 1 first-party imports checked" in out


def test_unresolved_import_exits_one_and_names_file_line_and_target(
    harness: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _write(harness, {"bad.py": "x = 1\nfrom pkg.defs import Gone\nimport pkg.nowhere\n"})

    assert cli.main([]) == 1

    err = capsys.readouterr().err
    assert "bad.py:2: pkg.defs:Gone (name not defined)" in err
    assert "bad.py:3: pkg.nowhere (module not found)" in err
    assert "no allowlist" in err


def test_json_output_lists_findings(harness: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _write(harness, {"bad.py": "import pkg.nowhere\n"})

    assert cli.main(["--json"]) == 1

    payload = json.loads(capsys.readouterr().out)
    assert payload["files"] == 4
    assert payload["imports"] == 2
    assert payload["unparsable"] == []
    assert [(item["line"], item["target"], item["reason"]) for item in payload["findings"]] == [
        (1, "pkg.nowhere", "module not found")
    ]


def test_scan_without_python_files_fails_instead_of_passing_silently(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    empty = tmp_path / "pkg"
    empty.mkdir()
    monkeypatch.setattr(cli, "HARNESS_SRC", empty)

    assert cli.main([]) == 2
    assert "nothing was scanned" in capsys.readouterr().err


def test_unparsable_file_is_a_loud_failure_not_a_pass(harness: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _write(harness, {"broken.py": "def (:\n"})

    assert cli.main([]) == 2
    assert "could not parse" in capsys.readouterr().err


def test_findings_outrank_an_unparsable_file(harness: Path) -> None:
    _write(harness, {"broken.py": "def (:\n", "bad.py": "import pkg.nowhere\n"})

    assert cli.main([]) == 1


def test_package_and_scan_check_the_server_tree_against_the_harness(
    tmp_path: Path, harness: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    app = _write(tmp_path / "app", {"__init__.py": "", "svc.py": "from pkg.defs import A, Gone\n"})
    _write(harness, {"bad.py": "import pkg.nowhere\n"})

    code = cli.main(["--package", f"pkg={harness}", "--package", f"app={app}", "--scan", "app"])

    assert code == 1
    err = capsys.readouterr().err
    assert "svc.py:1: pkg.defs:Gone" in err
    assert "bad.py" not in err


@pytest.mark.parametrize("value", ["pkg", "pkg=/does/not/exist", "not-an-identifier=."])
def test_invalid_package_argument_is_rejected(value: str, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as raised:
        cli.main(["--package", value])

    assert raised.value.code == 2
    assert "--package expects NAME=DIR" in capsys.readouterr().err


def test_scan_name_without_a_matching_package_is_rejected(harness: Path, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as raised:
        cli.main(["--package", f"pkg={harness}", "--scan", "app"])

    assert raised.value.code == 2
    assert "--scan names not given as --package: app" in capsys.readouterr().err


def test_incremental_skips_loudly_when_no_harness_source_changed(
    harness: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _write(harness, {"bad.py": "import pkg.nowhere\n"})
    monkeypatch.setattr(cli, "harness_sources_changed", lambda: False)

    assert cli.main(["--incremental"]) == 0
    assert "skipped (no harness source change)" in capsys.readouterr().out


def test_incremental_scans_when_harness_sources_changed(harness: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write(harness, {"bad.py": "import pkg.nowhere\n"})
    monkeypatch.setattr(cli, "harness_sources_changed", lambda: True)

    assert cli.main(["--incremental"]) == 1


def test_incremental_never_skips_an_explicit_package_scan(
    tmp_path: Path, harness: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli, "harness_sources_changed", lambda: False)
    app = _write(tmp_path / "app", {"__init__.py": "", "svc.py": "import app.nope\n"})

    assert cli.main(["--incremental", "--package", f"app={app}"]) == 1


@pytest.mark.parametrize(
    ("staged", "unstaged", "expected"),
    [
        ({"src/myrm_agent_harness/agent/x.py"}, set(), True),
        (set(), {"src/myrm_agent_harness/agent/x.py"}, True),
        ({"src/myrm_agent_harness/agent/_ARCH.md", "README.md", "scripts/x.py"}, set(), False),
        (set(), set(), False),
        (None, set(), True),
        (set(), None, True),
    ],
)
def test_harness_sources_changed_reads_staged_and_unstaged_python_changes(
    monkeypatch: pytest.MonkeyPatch, staged: set[str] | None, unstaged: set[str] | None, expected: bool
) -> None:
    answers = {("diff", "--cached", "--name-only"): staged, ("diff", "--name-only"): unstaged}
    monkeypatch.setattr(cli, "_git_paths", lambda *args: answers[args])

    assert cli.harness_sources_changed() is expected
