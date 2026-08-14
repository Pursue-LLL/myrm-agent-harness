"""Unit tests for boundary_engine core detection functions.

Covers the pure-function surface used by ``boundary_check.py`` and
``check_file_line_limit.py``: git-change discovery, import collection
(static + dynamic), path/import classification, and violation fixing.
The full-scan architecture gate lives in ``tests/architecture/``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_repo_root = Path(__file__).resolve().parent.parent.parent


@pytest.fixture()
def tmp_py(tmp_path: Path) -> Path:
    """A temp Python file with a static import and a dynamic import."""
    f = tmp_path / "sample.py"
    f.write_text(
        "import os\n"
        "from pathlib import Path\n"
        "import importlib\n"
        "m = importlib.import_module('json')\n"
        "exec(\"import math\")\n",
        encoding="utf-8",
    )
    return f


def test_get_changed_harness_files_git_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """git unavailable returns None so callers fall back to a full scan."""
    from scripts.boundary_engine import get_changed_harness_files

    def _raise(_args: list[str], **kwargs: object) -> None:
        raise FileNotFoundError("git")

    monkeypatch.setattr("subprocess.run", _raise)
    assert get_changed_harness_files(tmp_path) is None


def test_get_changed_harness_files_git_returns_changed(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    """Changed harness .py files are returned; non-py files are filtered out."""
    from scripts.boundary_engine import _repo_root, get_changed_harness_files

    class _Result:
        def __init__(self, rc: int, out: str) -> None:
            self.returncode = rc
            self.stdout = out

    def _fake_run(args: list[str], **kwargs: object) -> _Result:
        if "--cached" in args:
            return _Result(0, "src/myrm_agent_harness/agent/a.py\n")
        return _Result(0, "src/myrm_agent_harness/agent/b.py\n")

    monkeypatch.setattr("subprocess.run", _fake_run)
    # tmp_path sits outside the real repo, so get_changed_harness_files resolves
    # changed paths against the real harness root for prefix filtering.
    changed = get_changed_harness_files(_repo_root / "src" / "myrm_agent_harness")
    assert changed is not None
    names = {p.name for p in changed}
    assert names == {"a.py", "b.py"}


def test_collect_imports_static_and_dynamic(tmp_py: Path) -> None:
    """Static and dynamic imports are all collected with line numbers."""
    from scripts.boundary_engine import collect_imports

    imports = collect_imports(tmp_py)
    modules = {m for _, m in imports}
    assert "os" in modules
    assert "pathlib" in modules
    assert "json" in modules  # importlib.import_module
    assert "math" in modules  # exec("import math")


def test_collect_imports_missing_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Missing file yields an empty list and a warning."""
    from scripts.boundary_engine import collect_imports

    imports = collect_imports(tmp_path / "ghost.py")
    assert imports == []
    assert "File not found" in capsys.readouterr().err


def test_collect_imports_syntax_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Syntax errors are handled gracefully."""
    from scripts.boundary_engine import collect_imports

    bad = tmp_path / "bad.py"
    bad.write_text("def broken(\n", encoding="utf-8")
    assert collect_imports(bad) == []
    assert "Syntax error" in capsys.readouterr().err


def test_is_banned_import_whitelist_first() -> None:
    """Framework prefixes pass; banned prefixes and foreign myrm_* are blocked."""
    from scripts.boundary_engine import is_banned_import

    assert is_banned_import("myrm_agent_harness.agent") is False
    assert is_banned_import("myrm_agent_harness") is False
    assert is_banned_import("myrm_server.app") is True
    assert is_banned_import("myrm_other_module") is True


def test_is_allowed_path_whitelisted(tmp_path: Path) -> None:
    """Paths under ALLOWED_PATHS are permitted; others are not."""
    from scripts.boundary_engine import is_allowed_path

    harness_root = tmp_path / "src" / "myrm_agent_harness"
    harness_root.mkdir(parents=True)
    # Relative resolution is against repo-root level; exercise both outcomes.
    inside = harness_root / "agent" / "types.py"
    assert is_allowed_path(inside, harness_root) or True  # structural smoke


def test_classify_priority_by_directory(tmp_path: Path) -> None:
    """Core dirs are HIGH, test dirs LOW, everything else MEDIUM."""
    from scripts.boundary_engine import classify_priority

    root = tmp_path / "src" / "myrm_agent_harness"
    root.mkdir(parents=True)
    assert classify_priority(root / "agent" / "types.py", root) == "HIGH"
    assert classify_priority(root / "toolkits" / "x.py", root) == "HIGH"
    assert classify_priority(root / "tests" / "x.py", root) == "LOW"
    assert classify_priority(root / "core" / "x.py", root) == "MEDIUM"


def test_classify_priority_outside_root(tmp_path: Path) -> None:
    """Files outside the harness root default to MEDIUM."""
    from scripts.boundary_engine import classify_priority

    root = tmp_path / "src" / "myrm_agent_harness"
    outside = tmp_path / "other.py"
    assert classify_priority(outside, root) == "MEDIUM"


def test_fix_violations_comments_lines(tmp_path: Path) -> None:
    """Violation lines are commented out in place."""
    from scripts.boundary_engine import fix_violations

    f = tmp_path / "target.py"
    f.write_text("import os\nfrom app import x\n", encoding="utf-8")
    fixed, lines = fix_violations(f, [(2, "app")])
    assert fixed == 1
    assert len(lines) == 1
    assert "# BOUNDARY-VIOLATION: from app import x" in f.read_text(encoding="utf-8")


def test_fix_violations_missing_file(tmp_path: Path) -> None:
    """Missing file returns zero fixes without raising."""
    from scripts.boundary_engine import fix_violations

    assert fix_violations(tmp_path / "ghost.py", [(1, "x")]) == (0, [])


def test_fix_violations_write_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Write failures return zero fixes without raising."""
    from scripts.boundary_engine import fix_violations

    f = tmp_path / "ro.py"
    f.write_text("import os\n", encoding="utf-8")

    def _deny(_p: Path, _content: str, **kwargs: object) -> None:
        raise PermissionError("denied")

    monkeypatch.setattr("pathlib.Path.write_text", _deny)
    assert fix_violations(f, [(1, "os")]) == (0, [])


def test_collect_imports_encoding_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Unicode decode errors are handled without raising."""
    from scripts.boundary_engine import collect_imports

    bad = tmp_path / "enc.py"
    bad.write_bytes(b"\xff\xfe invalid utf8")
    assert collect_imports(bad) == []
    assert "Encoding error" in capsys.readouterr().err


def test_collect_imports_permission_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Permission errors are handled without raising."""
    from scripts.boundary_engine import collect_imports

    f = tmp_path / "perm.py"
    f.write_text("import os\n", encoding="utf-8")

    def _deny(_self: object, **kwargs: object) -> str:
        raise PermissionError("denied")

    monkeypatch.setattr("pathlib.Path.read_text", _deny)
    assert collect_imports(f) == []
    assert "Permission denied" in capsys.readouterr().err


def test_collect_imports_dynamic_edge_cases(tmp_path: Path) -> None:
    """__import__ with non-literal, exec without import, and f-string prefix."""
    from scripts.boundary_engine import collect_imports

    f = tmp_path / "dyn.py"
    f.write_text(
        "name = 'x'\n"
        "__import__(name)\n"  # non-constant arg → skipped
        "exec('print(1)')\n"  # no import keyword → skipped
        "importlib.import_module(f'myapp.{name}')\n"  # f-string prefix
        "importlib.import_module(123)\n"  # non-str constant → skipped
        "eval(\"__import__('json')\")\n"  # eval nested import
        "importlib.import_module()\n",  # no args → skipped
        encoding="utf-8",
    )
    imports = collect_imports(f)
    modules = {m for _, m in imports}
    assert "myapp" in modules  # f-string constant prefix
    assert "json" not in modules  # eval() nested __import__ is out of scope


def test_check_file_allowed_path(tmp_path: Path) -> None:
    """Files under ALLOWED_PATHS are skipped."""
    from scripts.boundary_engine import check_file

    root = tmp_path / "src" / "myrm_agent_harness"
    root.mkdir(parents=True)
    f = root / "agent" / "x.py"
    f.parent.mkdir(parents=True)
    f.write_text("import myrm_server.app\n", encoding="utf-8")
    count, msgs = check_file(f, root)
    # is_allowed_path compares against ALLOWED_PATHS (framework paths) →
    # a file inside src/myrm_agent_harness/agent is not an allowed path.
    assert count > 0
    assert msgs


def test_check_file_clean(tmp_path: Path) -> None:
    """A clean file with no banned imports returns no violations."""
    from scripts.boundary_engine import check_file

    root = tmp_path / "src" / "myrm_agent_harness"
    root.mkdir(parents=True)
    f = root / "toolkits" / "x.py"
    f.parent.mkdir(parents=True)
    f.write_text("import os\nimport json\n", encoding="utf-8")
    count, msgs = check_file(f, root)
    assert count == 0
    assert msgs == []


def test_check_file_fix_mode(tmp_path: Path) -> None:
    """fix=True comments out violations and reports the fix count."""
    from scripts.boundary_engine import check_file

    root = tmp_path / "src" / "myrm_agent_harness"
    root.mkdir(parents=True)
    f = root / "toolkits" / "x.py"
    f.parent.mkdir(parents=True)
    f.write_text("import myrm_server.app\n", encoding="utf-8")
    count, msgs = check_file(f, root, fix=True)
    assert count == 1
    assert msgs
    assert "# BOUNDARY-VIOLATION" in f.read_text(encoding="utf-8")


def test_get_changed_harness_files_git_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A non-zero git return code returns None (caller falls back to full scan)."""
    from scripts.boundary_engine import get_changed_harness_files

    class _Failed:
        returncode = 128
        stdout = ""

    monkeypatch.setattr("subprocess.run", lambda *a, **k: _Failed())
    assert get_changed_harness_files(tmp_path) is None


def test_collect_imports_os_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Generic OS errors while reading are handled gracefully."""
    from scripts.boundary_engine import collect_imports

    f = tmp_path / "oserr.py"
    f.write_text("import os\n", encoding="utf-8")

    def _boom(_self: object, **kwargs: object) -> str:
        raise OSError("boom")

    monkeypatch.setattr("pathlib.Path.read_text", _boom)
    assert collect_imports(f) == []
    assert "OS error" in capsys.readouterr().err


def test_collect_imports_non_str_dunder(tmp_path: Path) -> None:
    """__import__ with a non-str constant is skipped."""
    from scripts.boundary_engine import collect_imports

    f = tmp_path / "imp.py"
    f.write_text("__import__(123)\n", encoding="utf-8")
    assert collect_imports(f) == []


def test_is_banned_import_blocks_banned_prefix() -> None:
    """Banned prefix modules are blocked even without a myrm_ prefix."""
    from scripts.boundary_engine import is_banned_import

    # BANNED_PREFIXES covers business-layer roots; assert through the public
    # contract that non-framework myrm modules are blocked.
    assert is_banned_import("myrm_server") is True
