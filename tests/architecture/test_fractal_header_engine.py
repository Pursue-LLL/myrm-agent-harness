"""Tests for scripts/fractal_header_engine.py: synthesised [INPUT]/[OUTPUT]/[POS] module headers."""

from __future__ import annotations

import ast
import sys
import warnings
from pathlib import Path

import pytest

_repo_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_repo_root))

from scripts.check_fractal_docs import missing_io_headers
from scripts.fractal_header_engine import HeaderError, add_header, module_summary

pytestmark = pytest.mark.architecture

_TYPES_SOURCE = '''from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BranchDescriptor:
    """Descriptor of a session branch."""

    name: str
'''


def _package(tmp_path: Path) -> Path:
    package_root = tmp_path / "src" / "myrm_agent_harness"
    package_root.mkdir(parents=True)
    return package_root


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _header(path: Path, package_root: Path) -> str:
    return add_header(path.read_text(encoding="utf-8"), path, package_root).source


def _docstring(source: str) -> str:
    doc = ast.get_docstring(ast.parse(source))
    assert doc is not None
    return doc


def test_types_module_gets_synthesised_header(tmp_path: Path) -> None:
    package_root = _package(tmp_path)
    path = _write(package_root / "runtime" / "session_branching_types.py", _TYPES_SOURCE)

    result = add_header(path.read_text(encoding="utf-8"), path, package_root)

    assert result.summary == "Types and models for session branching."
    assert _docstring(result.source) == (
        "Types and models for session branching.\n\n"
        "[INPUT]\n- None (self-contained; standard library only)\n\n"
        "[OUTPUT]\n- BranchDescriptor: Descriptor of a session branch.\n\n"
        "[POS]\nTypes and models for session branching."
    )
    assert result.source.endswith(_TYPES_SOURCE)


def test_summary_comes_from_the_class_that_best_matches_the_module_name(tmp_path: Path) -> None:
    package_root = _package(tmp_path)
    source = '''class Unrelated:
    """Something else entirely."""


class SessionBranchingAndRewindEngine:
    """Forks sessions and rewinds timelines."""


def helper() -> None:
    """Small helper."""
'''
    path = _write(package_root / "runtime" / "session_branching_engine.py", source)

    result = add_header(source, path, package_root)

    assert result.summary == "Forks sessions and rewinds timelines."
    assert "- helper(): Small helper." in result.source


def test_internal_imports_are_resolved_with_target_summaries(tmp_path: Path) -> None:
    package_root = _package(tmp_path)
    _write(package_root / "runtime" / "context" / "flow_types.py", _TYPES_SOURCE)
    _write(package_root / "runtime" / "other.py", '"""Other helpers."""\n\n\ndef helper() -> None: ...\n')
    source = (
        "from myrm_agent_harness.runtime.context.flow_types import BranchDescriptor, Other\n"
        "from .flow_types import Third\n"
        "from ..other import helper\n"
        "\n\nclass FlowEngine:\n    pass\n"
    )
    path = _write(package_root / "runtime" / "context" / "flow_engine.py", source)

    doc = _docstring(add_header(source, path, package_root).source)

    assert "- runtime.context.flow_types::BranchDescriptor, Other, Third (POS: Types and models for flow.)" in doc
    assert "- runtime.other::helper (POS: Other helpers.)" in doc


def test_third_party_imports_are_listed_instead_of_claiming_stdlib_only(tmp_path: Path) -> None:
    package_root = _package(tmp_path)
    source = "import os, requests\nfrom pydantic import BaseModel\n\n\nclass Client(BaseModel):\n    pass\n"
    path = _write(package_root / "client.py", source)

    doc = _docstring(add_header(source, path, package_root).source)

    assert "- Third-party: pydantic, requests" in doc
    assert "standard library only" not in doc


def test_existing_docstring_prose_is_preserved(tmp_path: Path) -> None:
    package_root = _package(tmp_path)
    source = (
        '"""Does things.\n\nMore detail here.\n"""\n\nfrom __future__ import annotations\n\n\nclass Thing:\n    pass\n'
    )
    path = _write(package_root / "thing.py", source)

    result = add_header(source, path, package_root)

    assert _docstring(result.source).startswith("Does things.\n\nMore detail here.\n\n[INPUT]\n")
    assert result.summary == "Does things."
    assert result.source.endswith('"""\n\nfrom __future__ import annotations\n\n\nclass Thing:\n    pass\n')


def test_single_line_docstring_becomes_multiline(tmp_path: Path) -> None:
    package_root = _package(tmp_path)
    source = '"""Short."""\nX = 1\n'
    path = _write(package_root / "short.py", source)

    result = add_header(source, path, package_root)

    assert result.source.startswith('"""Short.\n\n[INPUT]\n')
    assert result.source.endswith('[POS]\nShort.\n"""\nX = 1\n')


def test_non_ascii_docstring_offsets_are_character_accurate(tmp_path: Path) -> None:
    package_root = _package(tmp_path)
    source = '"""处理表格压缩。\n\n详细说明：支持中文。\n"""\n\nLABEL = "表格"\n'
    path = _write(package_root / "table.py", source)

    result = add_header(source, path, package_root)

    assert _docstring(result.source).startswith("处理表格压缩。\n\n详细说明：支持中文。\n\n[INPUT]")
    assert result.source.endswith('"""\n\nLABEL = "表格"\n')


def test_dunder_all_limits_output_and_reexports_are_named(tmp_path: Path) -> None:
    package_root = _package(tmp_path)
    source = (
        "from .engine import Engine, Config\n\n__all__ = ['Engine', 'Config', 'make']\n\n\n"
        'def make() -> None:\n    """Build one."""\n\n\ndef hidden() -> None:\n    """Not exported."""\n'
    )
    path = _write(package_root / "pkg" / "__init__.py", source)

    doc = _docstring(add_header(source, path, package_root).source)

    assert "- make(): Build one." in doc
    assert "- Re-exports: Engine, Config" in doc
    assert "hidden" not in doc
    assert doc.splitlines()[0] == "Package facade for pkg."


def test_output_list_is_capped(tmp_path: Path) -> None:
    package_root = _package(tmp_path)
    source = "\n\n".join(f'class Item{i}:\n    """Item {i}."""' for i in range(20)) + "\n"
    path = _write(package_root / "many.py", source)

    doc = _docstring(add_header(source, path, package_root).source)

    assert doc.count("- Item") == 15
    assert "- (+5 more public symbols)" in doc


def test_backslashes_and_triple_quotes_cannot_break_the_generated_docstring(tmp_path: Path) -> None:
    package_root = _package(tmp_path)
    source = "class Matcher:\n    r'''Matches \\d+ digits and \"\"\" quotes.'''\n"
    path = _write(package_root / "matcher.py", source)

    new_source = add_header(source, path, package_root).source

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        compile(new_source, str(path), "exec")
    generated = _docstring(new_source)
    assert "\\" not in generated and '"""' not in generated
    assert "Matches /d+ digits and ''' quotes." in generated


def test_shebang_and_coding_lines_stay_first(tmp_path: Path) -> None:
    package_root = _package(tmp_path)
    source = "#!/usr/bin/env python3\n# -*- coding: utf-8 -*-\nimport os\n"
    path = _write(package_root / "tool.py", source)

    new_source = add_header(source, path, package_root).source

    assert new_source.splitlines()[:2] == ["#!/usr/bin/env python3", "# -*- coding: utf-8 -*-"]
    assert new_source.splitlines()[2].startswith('"""Tool.')
    assert new_source.endswith("\nimport os\n")


def test_header_changes_only_the_docstring(tmp_path: Path) -> None:
    package_root = _package(tmp_path)
    path = _write(package_root / "runtime" / "flow_types.py", _TYPES_SOURCE)

    new_tree = ast.parse(_header(path, package_root))

    assert [ast.dump(node) for node in new_tree.body[1:]] == [ast.dump(node) for node in ast.parse(_TYPES_SOURCE).body]


def test_added_header_satisfies_the_gate(tmp_path: Path) -> None:
    package_root = _package(tmp_path)
    path = _write(package_root / "runtime" / "flow_types.py", _TYPES_SOURCE)
    assert missing_io_headers(package_root) == [path]

    path.write_text(_header(path, package_root), encoding="utf-8")

    assert missing_io_headers(package_root) == []


@pytest.mark.parametrize(
    ("source", "reason"),
    [
        ("def broken(:\n", "cannot parse"),
        ('"single quoted docstring"\nX = 1\n', "triple-quoted"),
        ('"""Doc."""\r\nX = 1\r\n', "CRLF"),
    ],
)
def test_unsafe_files_are_refused(tmp_path: Path, source: str, reason: str) -> None:
    package_root = _package(tmp_path)
    path = _write(package_root / "unsafe.py", "")

    with pytest.raises(HeaderError, match=reason):
        add_header(source, path, package_root)


def test_module_summary_prefers_prose_then_pos_text_then_synthesis(tmp_path: Path) -> None:
    package_root = _package(tmp_path)
    prose = _write(package_root / "a.py", '"""Prose wins.\n\n[POS]\nIgnored."""\n')
    pos_only = _write(package_root / "b.py", '"""[POS]\nTracks the thing.\n\n[INPUT]\n- none\n"""\n')
    path_pos = _write(package_root / "c.py", '"""[POS]: src/pkg/c.py\n"""\nclass Worker:\n    """Works."""\n')
    bare = _write(package_root / "tidy_up_engine.py", "X = 1\n")

    assert module_summary(prose) == "Prose wins."
    assert module_summary(pos_only) == "Tracks the thing."
    assert module_summary(path_pos) == "Works."
    assert module_summary(bare) == "Tidy up engine."
