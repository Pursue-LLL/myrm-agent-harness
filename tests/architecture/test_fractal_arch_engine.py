"""Tests for scripts/fractal_arch_engine.py: table-aware ``_ARCH.md`` edits."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_repo_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_repo_root))

from scripts.fractal_arch_engine import add_subpackage_row, overview_of, render_new_arch, update_file_table
from scripts.validate_arch_inventory import scan_directory

pytestmark = pytest.mark.architecture

_BACKTICK_TABLE = """# demo/

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Facade. | ✅ |
| `alpha.py` | Core | Alpha. | ✅ |
| `omega.py` | Core | Omega. | ✅ |

Trailing prose.
"""


def _rows(text: str) -> list[str]:
    return [line for line in text.splitlines() if line.startswith("|") and ".py" in line]


def test_row_follows_header_style_and_sorted_position() -> None:
    result = update_file_table(_BACKTICK_TABLE, {"middle.py": "Middle."}, [])

    assert _rows(result) == [
        "| `__init__.py` | Package | Facade. | ✅ |",
        "| `alpha.py` | Core | Alpha. | ✅ |",
        "| `middle.py` | Core | Middle. | ✅ |",
        "| `omega.py` | Core | Omega. | ✅ |",
    ]
    assert result.endswith("Trailing prose.\n")


def test_unsorted_table_gets_the_row_appended_after_the_last_one() -> None:
    table = "| File | Role | Description |\n|---|---|---|\n| z.py | Core | Zed. |\n| a.py | Core | Ay. |\n"

    result = update_file_table(table, {"m.py": "Em."}, [])

    assert _rows(result) == ["| z.py | Core | Zed. |", "| a.py | Core | Ay. |", "| m.py | Core | Em. |"]


def test_plain_style_is_mimicked_when_most_rows_have_no_backticks() -> None:
    table = "| File | Role | Description | I/O/P |\n|---|---|---|---|\n| a.py | Core | Ay. | ✅ |\n| b.py | Core | Bee. | ✅ |\n"

    result = update_file_table(table, {"c.py": "Sea."}, [])

    assert "| c.py | Core | Sea. | ✅ |" in result


def test_chinese_header_uses_chinese_roles_and_omits_missing_columns() -> None:
    table = "| 文件 | 地位 | 职责 |\n|---|---|---|\n| `a.py` | 核心 | 甲。 |\n"

    result = update_file_table(table, {"__init__.py": "Facade.", "b.py": "Bee."}, [])

    assert "| `__init__.py` | 入口 | Facade. |" in result
    assert "| `b.py` | 核心 | Bee. |" in result


def test_role_only_table_carries_the_description_in_the_role_column() -> None:
    table = "| File | Role |\n|---|---|\n| a.py | Ay. |\n"

    assert "| b.py | Bee. |" in update_file_table(table, {"b.py": "Bee."}, [])


def test_unknown_columns_are_filled_with_a_dash() -> None:
    table = "| Module | Responsibility | Line Count Target |\n|---|---|---|\n| `a.py` | Ay. | < 300 |\n"

    assert "| `b.py` | Bee. | — |" in update_file_table(table, {"b.py": "Bee."}, [])


def test_roles_distinguish_types_and_packages() -> None:
    result = update_file_table(
        _BACKTICK_TABLE, {"flow_types.py": "Types.", "models.py": "Models.", "run.py": "Run."}, []
    )

    assert "| `flow_types.py` | Types | Types. | ✅ |" in result
    assert "| `models.py` | Types | Models. | ✅ |" in result
    assert "| `run.py` | Core | Run. | ✅ |" in result


def test_stale_rows_are_pruned_but_prose_mentions_stay() -> None:
    text = f"{_BACKTICK_TABLE}\nSee `alpha.py` for details.\n"

    result = update_file_table(text, {}, ["alpha.py"])

    assert "| `alpha.py`" not in result
    assert "See `alpha.py` for details." in result
    assert "| `omega.py` | Core | Omega. | ✅ |" in result


def test_pipe_characters_in_summaries_cannot_split_the_row() -> None:
    result = update_file_table(_BACKTICK_TABLE, {"pipe.py": "A | B"}, [])

    assert "| `pipe.py` | Core | A / B | ✅ |" in result


def test_document_without_a_file_table_gets_an_index_section() -> None:
    result = update_file_table("# demo/\n\nJust prose.\n", {"b.py": "Bee.", "a.py": "Ay."}, [])

    assert result == (
        "# demo/\n\nJust prose.\n\n## File & Submodule Index\n\n"
        "| File | Role | Description | I/O/P |\n|------|------|-------------|-------|\n"
        "| `a.py` | Core | Ay. | ✅ |\n| `b.py` | Core | Bee. | ✅ |\n"
    )


def test_largest_inventory_table_wins_over_other_tables() -> None:
    text = (
        "| Submodule | Description |\n|---|---|\n| sub/ | Child. |\n\n"
        "| File | Role | Description | I/O/P |\n|---|---|---|---|\n| a.py | Core | Ay. | ✅ |\n"
    )

    result = update_file_table(text, {"b.py": "Bee."}, [])

    assert result.index("| b.py") > result.index("| a.py")
    assert result.count("| b.py") == 1


def test_updated_table_satisfies_the_inventory_gate(tmp_path: Path) -> None:
    for name in ("__init__.py", "alpha.py", "omega.py", "fresh.py"):
        (tmp_path / name).write_text("X = 1\n", encoding="utf-8")
    (tmp_path / "_ARCH.md").write_text(update_file_table(_BACKTICK_TABLE, {"fresh.py": "Fresh."}, []), encoding="utf-8")

    report = scan_directory(tmp_path)

    assert report is not None
    assert report.missing_in_arch == () and report.extra_in_arch == ()


def test_new_arch_document_lists_every_file_and_passes_the_gate(tmp_path: Path) -> None:
    rows = {"__init__.py": "Package facade for demo.", "engine.py": "Runs the demo.", "engine_types.py": "Types."}
    for name in rows:
        (tmp_path / name).write_text("X = 1\n", encoding="utf-8")
    text = render_new_arch("demo", overview_of(rows), rows)
    (tmp_path / "_ARCH.md").write_text(text, encoding="utf-8")

    report = scan_directory(tmp_path)

    assert text.startswith("# demo/\n\n## Overview\n\nRuns the demo.\n")
    assert report is not None
    assert report.missing_in_arch == () and report.extra_in_arch == ()
    assert "| `engine_types.py` | Types | Types. | ✅ |" in text
    assert "| `__init__.py` | Package |" in text


def test_overview_prefers_an_implementation_module() -> None:
    assert overview_of({"__init__.py": "Facade.", "a_types.py": "Types.", "z_engine.py": "Engine."}) == "Engine."
    assert overview_of({"__init__.py": "Facade."}) == "Facade."
    assert overview_of({}) == ""


_PARENT = """# parent/

| Submodule | Description |
|-----------|-------------|
| alpha/ | Alpha package. See [alpha/_ARCH.md](alpha/_ARCH.md). |
| gamma/ | Gamma package. See [gamma/_ARCH.md](gamma/_ARCH.md). |
"""


def test_subpackage_row_is_inserted_in_sorted_order_with_a_link() -> None:
    result = add_subpackage_row(_PARENT, "beta", "Beta package.")

    assert result is not None
    lines = result.splitlines()
    assert lines[5] == "| beta/ | Beta package. See [beta/_ARCH.md](beta/_ARCH.md). |"
    assert lines[4].startswith("| alpha/") and lines[6].startswith("| gamma/")


def test_subpackage_row_is_not_duplicated_and_requires_a_subpackage_table() -> None:
    assert add_subpackage_row(_PARENT, "alpha", "Again.") is None
    assert add_subpackage_row("# parent/\n\n| File | Role |\n|---|---|\n| a.py | Core |\n", "beta", "Beta.") is None
    assert add_subpackage_row("# parent/\n\nProse only.\n", "beta", "Beta.") is None
