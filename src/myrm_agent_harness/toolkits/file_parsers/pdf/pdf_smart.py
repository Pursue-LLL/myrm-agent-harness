"""Smart PDF parser with OCR fallback for scanned documents.

[INPUT]
- pdf_content_extractor::extract_pdf_content (POS: Smart PDF extraction orchestrator. Auto-selects Text/Hybrid(embedded image)/Image(full-page render fallback) strategy. Scanned PDFs (sparse text layer) are additionally OCR'd via the optional PaddleOCR parser so text-only consumers (RAG ingestion, non-vision models) still get readable text. Supports Table Encapsulation to prevent RAG chunking from splitting tables, using L0 summaries to ensure retrieval accuracy.)
- base::FileParser (POS: File parser base classes and data structures)

[OUTPUT]
- SmartPDFParser: FileParser implementation with text/table extraction + OCR fallback

[POS]
PDF parser adapter over the smart extraction orchestrator. Returns plain text
with tables rendered inline; scanned PDFs (sparse text layer) are OCR'd so
text-only consumers (@-mentions, wiki imports, web downloads) read them too.
"""

from __future__ import annotations

from myrm_agent_harness.toolkits.file_parsers.base import FileParser

from .pdf_content_extractor import (
    PDFExtractConfig,
    extract_pdf_content,
)


class SmartPDFParser(FileParser):
    """PDF parser that returns text (tables inline) with best-effort OCR fallback.

    Text-rich PDFs are parsed via pdfplumber (tables rendered inline, same as
    PDFPlumberParser); scanned PDFs (sparse text) are rendered and OCR'd so the
    result stays readable without a vision model. Embedded-image extraction is
    disabled because this parser targets text output only.
    """

    _SUPPORTED_EXTENSIONS: tuple[str, ...] = (".pdf",)

    def __init__(self, config: PDFExtractConfig | None = None) -> None:
        self._config = config or PDFExtractConfig(
            extract_embedded_images=False,
            table_format="inline",
        )

    @property
    def supported_extensions(self) -> list[str]:
        return list(self._SUPPORTED_EXTENSIONS)

    async def parse(self, file_path: str) -> str:
        result = await extract_pdf_content(file_path, self._config)
        return result.text
