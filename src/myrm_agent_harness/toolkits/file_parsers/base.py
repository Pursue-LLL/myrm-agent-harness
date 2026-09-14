"""File parser base classes and data structures

Provides abstract base class and common data structures for all file parsers.

[INPUT]
- (none)

[OUTPUT]
- PDFHeading: resolved document heading (level/title/page)
- PDFTable: PDF table data structure with encapsulated metadata for high-precision RAG
- PDFParseResult: PDF parsing result
- FileParser: Abstract base class for file parsers

[POS]
File parser base classes and data structures
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class PDFHeading:
    """A resolved document heading.

    Single source of truth for the document structure consumed by
    ``file_read(parse_mode='structure')``; produced from PDF bookmarks or from
    text/font detection when bookmarks are absent or carry no structure.
    """

    level: int  # 1-6
    title: str
    page_num: int  # 1-based


@dataclass
class PDFTable:
    """PDF table data structure with encapsulated metadata for high-precision RAG."""

    page_number: int
    table_index: int
    data: list[list[str]]
    id: str = ""  # Unique ID: table_{page}_{index}
    markdown: str = ""  # Pre-rendered markdown for L2 detailed representation
    summary_l0: str = ""  # Heuristic summary for L0 semantic indexing
    bbox: tuple[float, float, float, float] | None = None
    column_starts: tuple[float, ...] | None = None  # Column x anchors for cross-page stitching
    page_range: tuple[int, int] | None = None  # Inclusive page span when stitched across pages


@dataclass
class PDFParseResult:
    """PDF parsing result"""

    text: str
    tables: list[PDFTable]
    metadata: dict[str, str | int]
    headings: list[PDFHeading] = field(default_factory=list)


class FileParser(ABC):
    """Abstract base class for file parsers"""

    @abstractmethod
    async def parse(self, file_path: str) -> str:
        """Parse file and return text content

        Args:
            file_path: File path

        Returns:
            Parsed text content
        """

    @property
    @abstractmethod
    def supported_extensions(self) -> list[str]:
        """List of supported file extensions"""
