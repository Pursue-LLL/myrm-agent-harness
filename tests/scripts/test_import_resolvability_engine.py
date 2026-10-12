"""Unit tests for scripts.import_resolvability_engine.

Every case builds a synthetic package under ``tmp_path`` (root name ``pkg``, plus ``app`` for the
cross-root cases), so the tests are hermetic and neither import nor read the harness tree.
"""

from __future__ import annotations

import sys
from pathlib import Path

_repo_root = Path(__file__).resolve().parent.parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

from scripts.import_resolvability_engine import MODULE_MISSING, NAME_MISSING, Report, analyze

_BASE = {
    "__init__.py": "",
    "sub/__init__.py": "",
    "sub/leaf.py": "VALUE = 1\n",
    "top.py": "VALUE = 1\n",
}


def _tree(tmp_path: Path, name: str, files: dict[str, str]) -> Path:
    root = tmp_path / name
    for rel, text in files.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return root


def _scan(tmp_path: Path, files: dict[str, str]) -> Report:
    return analyze({"pkg": _tree(tmp_path, "pkg", {**_BASE, **files})})


def _findings(report: Report) -> set[tuple[str, str, str]]:
    return {(finding.path.name, finding.target, finding.reason) for finding in report.findings}


def test_clean_tree_reports_nothing_and_counts_first_party_imports(tmp_path: Path) -> None:
    report = _scan(
        tmp_path, {"user.py": "import os\nimport pkg.top\nfrom pkg.sub import leaf\nfrom collections import abc\n"}
    )

    assert report.findings == ()
    assert report.imports_checked == 2
    assert report.files_scanned == 5


def test_missing_module_is_reported_for_both_import_forms(tmp_path: Path) -> None:
    report = _scan(tmp_path, {"user.py": "import pkg.gone\nfrom pkg.sub.gone import thing\n"})

    assert _findings(report) == {
        ("user.py", "pkg.gone", MODULE_MISSING),
        ("user.py", "pkg.sub.gone", MODULE_MISSING),
    }
    assert [finding.line for finding in report.findings] == [1, 2]


def test_submodules_and_subpackages_resolve_through_from_imports(tmp_path: Path) -> None:
    report = _scan(tmp_path, {"user.py": "from pkg import sub, top\nfrom pkg.sub import leaf\nimport pkg.sub.leaf\n"})

    assert report.findings == ()


def test_relative_imports_resolve_against_the_importing_package(tmp_path: Path) -> None:
    report = _scan(
        tmp_path,
        {
            "sub/mod.py": "from . import leaf\nfrom .. import top\nfrom .leaf import VALUE\nfrom ..top import VALUE as T\n",
            "sub/broken.py": "from .gone import thing\nfrom ..gone import thing\n",
        },
    )

    assert _findings(report) == {
        ("broken.py", "pkg.sub.gone", MODULE_MISSING),
        ("broken.py", "pkg.gone", MODULE_MISSING),
    }


def test_relative_import_inside_a_package_init_is_relative_to_that_package(tmp_path: Path) -> None:
    report = _scan(tmp_path, {"sub/__init__.py": "from .leaf import VALUE\nfrom . import leaf\nfrom .gone import x\n"})

    assert _findings(report) == {("__init__.py", "pkg.sub.gone", MODULE_MISSING)}


def test_imports_hidden_in_functions_try_blocks_and_type_checking_are_checked(tmp_path: Path) -> None:
    source = (
        "from typing import TYPE_CHECKING\n"
        "if TYPE_CHECKING:\n"
        "    from pkg.gone_typing import T\n"
        "def work() -> None:\n"
        "    try:\n"
        "        from pkg.gone_lazy import run\n"
        "    except Exception:\n"
        "        run = None\n"
    )

    report = _scan(tmp_path, {"user.py": source})

    assert _findings(report) == {
        ("user.py", "pkg.gone_typing", MODULE_MISSING),
        ("user.py", "pkg.gone_lazy", MODULE_MISSING),
    }


def test_third_party_and_stdlib_imports_are_out_of_scope(tmp_path: Path) -> None:
    report = _scan(tmp_path, {"user.py": "import numpy\nimport os.path\nfrom collections import OrderedDict\n"})

    assert report.findings == ()
    assert report.imports_checked == 0


def test_names_bound_at_import_time_resolve(tmp_path: Path) -> None:
    defs = (
        "class A: ...\n"
        "def f() -> None: ...\n"
        "async def g() -> None: ...\n"
        "X = 1\n"
        "Y: int = 2\n"
        "P, (Q, *R) = 1, (2, 3)\n"
        "type Alias = int\n"
        "for loop_name in range(3):\n"
        "    pass\n"
        "with open(__file__) as handle:\n"
        "    pass\n"
    )
    names = "A, f, g, X, Y, P, Q, R, Alias, loop_name, handle"

    report = _scan(tmp_path, {"defs.py": defs, "user.py": f"from pkg.defs import {names}\n"})

    assert report.findings == ()


def test_names_not_bound_at_import_time_are_reported(tmp_path: Path) -> None:
    defs = "Declared: int\ndef outer() -> None:\n    inner = 1\nclass K:\n    attribute = 1\n"

    report = _scan(
        tmp_path,
        {"defs.py": defs, "user.py": "from pkg.defs import Declared, inner, attribute, outer, K\n"},
    )

    assert _findings(report) == {
        ("user.py", "pkg.defs:Declared", NAME_MISSING),
        ("user.py", "pkg.defs:inner", NAME_MISSING),
        ("user.py", "pkg.defs:attribute", NAME_MISSING),
    }


def test_names_bound_inside_conditionals_and_try_blocks_resolve(tmp_path: Path) -> None:
    cond = (
        "import sys\n"
        "if sys.platform == 'win32':\n"
        "    def win_only() -> None: ...\n"
        "else:\n"
        "    def posix_only() -> None: ...\n"
        "try:\n"
        "    from fast_impl import impl\n"
        "except ImportError:\n"
        "    fallback = None\n"
        "finally:\n"
        "    cleaned = True\n"
        "match sys.argv:\n"
        "    case []:\n"
        "        matched = 1\n"
    )

    report = _scan(
        tmp_path,
        {
            "cond.py": cond,
            "user.py": "from pkg.cond import win_only, posix_only, impl, fallback, cleaned, matched, sys\n",
        },
    )

    assert report.findings == ()


def test_import_aliases_bind_the_alias_not_the_original_name(tmp_path: Path) -> None:
    hub = "from pkg.defs import A as Renamed\nimport os.path\nimport pkg.top as short\n"

    report = _scan(
        tmp_path,
        {
            "defs.py": "class A: ...\n",
            "hub.py": hub,
            "user.py": "from pkg.hub import Renamed, os, short\nfrom pkg.hub import A\n",
        },
    )

    assert _findings(report) == {("user.py", "pkg.hub:A", NAME_MISSING)}


def test_dunder_all_entries_count_even_when_defined_elsewhere(tmp_path: Path) -> None:
    exports = '__all__ = ["Declared"]\n__all__ += ["More"]\n'

    report = _scan(tmp_path, {"exports.py": exports, "user.py": "from pkg.exports import Declared, More, Other\n"})

    assert _findings(report) == {("user.py", "pkg.exports:Other", NAME_MISSING)}


def test_star_imports_export_public_names_unless_dunder_all_narrows_them(tmp_path: Path) -> None:
    files = {
        "impl.py": "def public() -> None: ...\ndef _private() -> None: ...\n",
        "hub.py": "from pkg.impl import *\n",
        "narrow_impl.py": '__all__ = ["_private"]\ndef public() -> None: ...\ndef _private() -> None: ...\n',
        "narrow_hub.py": "from pkg.narrow_impl import *\n",
        "user.py": ("from pkg.hub import public, _private\nfrom pkg.narrow_hub import _private as p, public as q\n"),
    }

    report = _scan(tmp_path, files)

    assert _findings(report) == {
        ("user.py", "pkg.hub:_private", NAME_MISSING),
        ("user.py", "pkg.narrow_hub:public", NAME_MISSING),
    }


def test_star_import_cycles_terminate(tmp_path: Path) -> None:
    files = {
        "a.py": "from pkg.b import *\n",
        "b.py": "from pkg.a import *\n",
        "user.py": "from pkg.a import nothing\n",
    }

    report = _scan(tmp_path, files)

    assert _findings(report) == {("user.py", "pkg.a:nothing", NAME_MISSING)}


def test_modules_with_a_dynamic_namespace_accept_every_name(tmp_path: Path) -> None:
    files = {
        "lazy.py": "def __getattr__(name: str) -> object:\n    return name\n",
        "mutated.py": "globals().update({'made_up': 1})\n",
        "user.py": "from pkg.lazy import anything\nfrom pkg.mutated import made_up, other\n",
    }

    report = _scan(tmp_path, files)

    assert report.findings == ()


def test_unparsable_file_exists_as_a_module_and_is_reported(tmp_path: Path) -> None:
    files = {
        "broken.py": "def (:\nfrom pkg.gone import thing\n",
        "user.py": "import pkg.broken\nfrom pkg.broken import anything\n",
    }

    report = _scan(tmp_path, files)

    assert report.findings == ()
    assert [path.name for path in report.unparsable] == ["broken.py"]


def test_scan_limits_which_roots_are_checked_but_names_resolve_across_all(tmp_path: Path) -> None:
    pkg = _tree(tmp_path, "pkg", {**_BASE, "defs.py": "class A: ...\n", "bad.py": "import pkg.gone\n"})
    app = _tree(tmp_path, "app", {"__init__.py": "", "svc.py": "from pkg.defs import A, Gone\nimport app.nope\n"})

    report = analyze({"pkg": pkg, "app": app}, scan=["app"])

    assert _findings(report) == {
        ("svc.py", "pkg.defs:Gone", NAME_MISSING),
        ("svc.py", "app.nope", MODULE_MISSING),
    }
    assert report.files_scanned == 2


def test_findings_are_sorted_by_path_line_and_target(tmp_path: Path) -> None:
    files = {"b.py": "import pkg.zz\nimport pkg.aa\n", "a.py": "import pkg.mm\n"}

    report = _scan(tmp_path, files)

    assert [(finding.path.name, finding.line) for finding in report.findings] == [("a.py", 1), ("b.py", 1), ("b.py", 2)]


def test_bytecode_directories_are_ignored(tmp_path: Path) -> None:
    report = _scan(tmp_path, {"__pycache__/stale.py": "import pkg.gone\n"})

    assert report.findings == ()
    assert report.files_scanned == 4
