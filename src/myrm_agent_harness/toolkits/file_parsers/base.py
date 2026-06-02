"""File parser base classes and data structures

Provides abstract base class and common data structures for all file parsers.

[INPUT]
- (none)

[OUTPUT]
- PDFTable: PDF table data structure with encapsulated metadata for h...
- PDFParseResult: PDF parsing result
- FileParser: Abstract base class for file parsers

[POS]
File parser base classes and data structures
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


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


@dataclass
class PDFParseResult:
    """PDF parsing result"""

    text: str
    tables: list[PDFTable]
    metadata: dict[str, str | int]


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
