"""Office write guard for file_ops text writes (edge path).

[INPUT]
- file_ops write paths and content (text-only tool surface)

[OUTPUT]
- OfficeWriteGuard.apply: warnings when Office extensions receive risky text writes

[POS]
Secondary guard — primary Office fidelity path is OfficeBashAudit after bash execution.
"""

from __future__ import annotations

from myrm_agent_harness.agent.meta_tools.file_ops.utils.office_scope import (
    is_office_docx_path,
    is_office_xlsx_path,
)


class OfficeWriteGuard:
    """Warn when file_write/file_edit attempts text writes to Office binary paths."""

    _RISKY_OFFICE_PATTERNS = (
        "paragraph.text =",
        "cell.text =",
        "pandas.read_excel",
        "to_excel(",
    )

    @staticmethod
    def apply(path: str, post_content: str) -> tuple[str, list[str]]:
        """Return content unchanged plus warnings for risky Office text writes."""
        warnings: list[str] = []
        if not (is_office_docx_path(path) or is_office_xlsx_path(path)):
            return post_content, warnings

        lowered = post_content.lower()
        if any(pattern in lowered for pattern in OfficeWriteGuard._RISKY_OFFICE_PATTERNS):
            warnings.append(
                "Office files should be edited via bash_code_execute_tool with XML-level "
                "or openpyxl-safe patterns — file_edit text writes cannot preserve binary layout."
            )
            return post_content, warnings

        if is_office_docx_path(path) or is_office_xlsx_path(path):
            warnings.append(
                "Direct text write to an Office file path is unsupported; use bash_code_execute_tool "
                "with office-document skill patterns instead."
            )
        return post_content, warnings
