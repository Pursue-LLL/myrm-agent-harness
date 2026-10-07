"""Table-aware edits of ``_ARCH.md`` files (fractal doc level L3) for the fractal-docs fixer.

Rows are generated to match the table they join: column meaning comes from the header
(File/Role/Description/I-O-P and the Chinese variants), backtick style from the existing
rows, and the position from the existing order (sorted tables stay sorted). File-row
detection reuses ``validate_arch_inventory`` so the fixer and the gate cannot disagree.

[INPUT]
- scripts/validate_arch_inventory.py::first_table_cell, is_inventory_file_cell

[OUTPUT]
- update_file_table(): add rows for undocumented ``.py`` files and prune rows of deleted files
- render_new_arch() / overview_of(): ``_ARCH.md`` for a directory that has none, and its overview sentence
- add_subpackage_row(): index a newly documented sub-package in its parent ``_ARCH.md``

[POS]
Documentation half of scripts/fix_fractal_docs.py; pure text-in/text-out, no filesystem access.
"""

from __future__ import annotations

import re
import sys
from collections.abc import Callable, Collection, Mapping
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from validate_arch_inventory import first_table_cell, is_inventory_file_cell

_SEPARATOR_RE = re.compile(r"^\|[\s:|-]+\|?$")
_SUBPACKAGE_RE = re.compile(r"^[A-Za-z_]\w*/$")
_ROLE_HEADERS = frozenset({"role", "地位", "tier", "classification", "type", "类型"})
_DESC_HEADERS = frozenset(
    {"description", "职责", "responsibility", "说明", "描述", "purpose", "pos", "作用", "用途"},
)
_CJK_HEADERS = frozenset({"地位", "类型"})
_TYPES_STEMS = ("types", "models", "schemas", "contracts")
_DEFAULT_KINDS = ["name", "role", "desc", "iop"]
_TABLE_HEAD = "| File | Role | Description | I/O/P |\n|------|------|-------------|-------|"

_RowPredicate = Callable[[str], bool]


def update_file_table(text: str, add: Mapping[str, str], remove: Collection[str]) -> str:
    """Return ``text`` with rows for ``add`` (file name -> summary) inserted and rows for ``remove`` pruned."""
    lines = [line for line in text.split("\n") if not (_is_file_row(line) and first_table_cell(line) in remove)]
    if not add:
        return "\n".join(lines)
    starts = [start for start in _block_starts(lines) if _rows(lines, start, _is_file_row)]
    if not starts:
        return _append_section(lines, add)
    start = max(starts, key=lambda s: len(_rows(lines, s, _is_file_row)))
    for name in sorted(add):
        _insert_row(lines, start, name, add[name], _is_file_row)
    return "\n".join(lines)


def overview_of(rows: Mapping[str, str]) -> str:
    """One-sentence directory description: the summary of its first implementation module (not facade or types)."""
    ordered = sorted(rows.items())
    core = [summary for name, summary in ordered if _role(name, cjk=False) == "Core"]
    return (core or [summary for _, summary in ordered] or [""])[0]


def render_new_arch(directory_name: str, overview: str, rows: Mapping[str, str]) -> str:
    """``_ARCH.md`` for a directory without one: overview plus a complete file index."""
    table = "\n".join(_new_row(name, summary) for name, summary in sorted(rows.items()))
    return f"# {directory_name}/\n\n## Overview\n\n{overview}\n\n## File & Submodule Index\n\n{_TABLE_HEAD}\n{table}\n"


def add_subpackage_row(text: str, child: str, overview: str) -> str | None:
    """Index ``child/`` in the parent's sub-package table; ``None`` when there is no such table or it is listed."""
    lines = text.split("\n")
    name = f"{child}/"
    if any(_is_subpackage_row(line) and first_table_cell(line) == name for line in lines):
        return None
    starts = [start for start in _block_starts(lines) if _rows(lines, start, _is_subpackage_row)]
    if not starts:
        return None
    start = max(starts, key=lambda s: len(_rows(lines, s, _is_subpackage_row)))
    _insert_row(lines, start, name, f"{overview} See [{name}_ARCH.md]({name}_ARCH.md).", _is_subpackage_row)
    return "\n".join(lines)


# ------------------------------------------------------------------------- tables


def _cells(line: str) -> list[str]:
    parts = [cell.strip() for cell in line.strip().split("|")]
    return parts[1:-1] if line.strip().endswith("|") else parts[1:]


def _is_table(line: str) -> bool:
    return line.strip().startswith("|")


def _is_file_row(line: str) -> bool:
    cell = first_table_cell(line)
    return bool(cell) and is_inventory_file_cell(cell)


def _is_subpackage_row(line: str) -> bool:
    cell = first_table_cell(line)
    return bool(cell) and bool(_SUBPACKAGE_RE.match(cell))


def _block_starts(lines: list[str]) -> list[int]:
    """Line index where each contiguous run of table lines begins."""
    starts: list[int] = []
    previous = False
    for index, line in enumerate(lines):
        current = _is_table(line)
        if current and not previous:
            starts.append(index)
        previous = current
    return starts


def _rows(lines: list[str], start: int, is_row: _RowPredicate) -> list[int]:
    """Indices of the matching rows in the table block beginning at ``start``."""
    rows: list[int] = []
    index = start
    while index < len(lines) and _is_table(lines[index]):
        if is_row(lines[index]):
            rows.append(index)
        index += 1
    return rows


def _layout(lines: list[str], start: int, sample: int) -> tuple[list[str], bool]:
    """Column kinds (name/role/desc/iop/blank) of the table at ``start`` and whether its role words are Chinese."""
    has_header = start + 1 < len(lines) and _SEPARATOR_RE.match(lines[start + 1].strip())
    if not has_header:
        return ["name", "desc", *["blank"] * max(len(_cells(lines[sample])) - 2, 0)], False
    header = _cells(lines[start])
    kinds = ["name"]
    for cell in header[1:]:
        key = cell.replace("`", "").strip().lower()
        if "i/o/p" in key:
            kinds.append("iop")
        elif key in _ROLE_HEADERS:
            kinds.append("role")
        elif key in _DESC_HEADERS:
            kinds.append("desc")
        else:
            kinds.append("blank")
    if "desc" not in kinds and len(kinds) > 1:
        kinds[kinds.index("role") if "role" in kinds else 1] = "desc"
    return kinds, any(cell in _CJK_HEADERS for cell in header)


def _role(name: str, *, cjk: bool) -> str:
    if name == "__init__.py" or name.endswith("/"):
        return "入口" if cjk else "Package"
    if cjk:
        return "核心"
    stem = name.removesuffix(".py")
    is_types = stem in _TYPES_STEMS or any(stem.endswith(f"_{suffix}") for suffix in _TYPES_STEMS)
    return "Types" if is_types else "Core"


def _row(kinds: list[str], name: str, summary: str, *, role: str, backtick: bool) -> str:
    values = {
        "name": f"`{name}`" if backtick else name,
        "role": role,
        "desc": summary.replace("|", "/"),
        "iop": "✅",
        "blank": "—",
    }
    return "| " + " | ".join(values[kind] for kind in kinds) + " |"


def _new_row(name: str, summary: str) -> str:
    return _row(_DEFAULT_KINDS, name, summary, role=_role(name, cjk=False), backtick=True)


def _insert_row(lines: list[str], start: int, name: str, summary: str, is_row: _RowPredicate) -> None:
    """Insert one row into the table at ``start``: sorted position if the table is sorted, else after its last row."""
    rows = _rows(lines, start, is_row)
    names = [first_table_cell(lines[i]) or "" for i in rows]
    kinds, cjk = _layout(lines, start, rows[0])
    backticked = sum(lines[i].strip().split("|")[1].strip().startswith("`") for i in rows)
    row = _row(kinds, name, summary, role=_role(name, cjk=cjk), backtick=backticked * 2 > len(rows))
    index = rows[-1] + 1
    if names == sorted(names):
        index = next((i for i, other in zip(rows, names, strict=True) if other > name), index)
    lines.insert(index, row)


def _append_section(lines: list[str], add: Mapping[str, str]) -> str:
    body = "\n".join(lines).rstrip("\n")
    table = "\n".join(_new_row(name, summary) for name, summary in sorted(add.items()))
    return f"{body}\n\n## File & Submodule Index\n\n{_TABLE_HEAD}\n{table}\n"
