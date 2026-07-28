"""Office file scope detection for write-fidelity guards.

[INPUT]
- Local filesystem paths from file_ops and bash audit

[OUTPUT]
- is_office_docx_path / is_office_xlsx_path helpers

[POS]
Extension-based scope for Office write guards — no server imports.
"""

from __future__ import annotations

from pathlib import Path

_DOCX_EXTENSIONS = frozenset({".docx", ".doc"})
_XLSX_EXTENSIONS = frozenset({".xlsx", ".xls", ".xlsm"})


def is_office_docx_path(file_path: str) -> bool:
    """True when the path is a Word document we can OPC-audit."""
    return Path(file_path).suffix.lower() in _DOCX_EXTENSIONS


def is_office_xlsx_path(file_path: str) -> bool:
    """True when the path is an Excel workbook we can formula-audit."""
    return Path(file_path).suffix.lower() in _XLSX_EXTENSIONS
