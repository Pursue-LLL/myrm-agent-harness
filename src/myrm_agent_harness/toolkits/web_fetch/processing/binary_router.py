"""Binary content detection and routing.

When HttpFetcher receives a non-text response (PDF, image, Office documents),
this module detects the content type via a three-layer strategy and routes
the raw bytes to the appropriate file parser for extraction.

[INPUT]
- web_fetch.fetchers.protocols::FetchResult (POS: Fetcher protocol types)
- toolkits.file_parsers (POS: File parsers toolkit)

[OUTPUT]
- route_binary_content: Detect and parse binary content from a FetchResult

[POS]
Binary content detection and routing for non-HTML URLs (PDF, images, documents).
Three-layer detection: Content-Type → Content-Disposition → Magic Bytes.
"""

from __future__ import annotations

import logging
import re
import tempfile
from pathlib import Path

from langchain_core.documents import Document

logger = logging.getLogger(__name__)

_MAX_BINARY_SIZE = 20 * 1024 * 1024  # 20 MB safety limit

_CONTENT_TYPE_MAP: dict[str, str] = {
    "application/pdf": ".pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
    "application/msword": ".doc",
    "application/vnd.ms-excel": ".xls",
    "application/vnd.ms-powerpoint": ".ppt",
    "image/png": ".png",
    "image/jpeg": ".jpeg",
    "image/webp": ".webp",
    "image/bmp": ".bmp",
    "image/tiff": ".tiff",
}

_MAGIC_SIGNATURES: list[tuple[bytes, str]] = [
    (b"%PDF", ".pdf"),
    (b"\x89PNG\r\n\x1a\n", ".png"),
    (b"\xff\xd8\xff", ".jpeg"),
    (b"RIFF", ".webp"),  # RIFF....WEBP (check sub-format below)
    (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", ".doc"),  # OLE2 Compound (legacy Office)
    (b"PK\x03\x04", ".zip"),  # ZIP-based (DOCX/XLSX/PPTX)
]

_CD_FILENAME_RE = re.compile(r"filename\*?=(?:UTF-8''|utf-8'')?[\"']?([^\"';\s]+)", re.IGNORECASE)


def _detect_extension_from_content_type(content_type: str) -> str | None:
    """Layer 1: Map Content-Type header to file extension."""
    ct = content_type.split(";")[0].strip().lower()
    return _CONTENT_TYPE_MAP.get(ct)


def _detect_extension_from_disposition(headers: dict[str, str]) -> str | None:
    """Layer 2: Extract filename from Content-Disposition header."""
    cd = headers.get("content-disposition") or headers.get("Content-Disposition") or ""
    match = _CD_FILENAME_RE.search(cd)
    if not match:
        return None
    filename = match.group(1).strip("\"'")
    ext = Path(filename).suffix.lower()
    return ext if ext else None


def _detect_extension_from_magic(data: bytes) -> str | None:
    """Layer 3: Identify format from first bytes (magic signature)."""
    if len(data) < 8:
        return None

    for sig, ext in _MAGIC_SIGNATURES:
        if data[: len(sig)] == sig:
            if ext == ".webp" and len(data) >= 12 and data[8:12] != b"WEBP":
                continue
            if ext == ".zip":
                return _refine_zip_extension(data)
            return ext

    return None


def _refine_zip_extension(data: bytes) -> str:
    """Distinguish DOCX/XLSX/PPTX from generic ZIP by internal structure."""
    import zipfile
    from io import BytesIO

    try:
        with zipfile.ZipFile(BytesIO(data)) as zf:
            names = zf.namelist()
            if any(n.startswith("word/") for n in names):
                return ".docx"
            if any(n.startswith("xl/") for n in names):
                return ".xlsx"
            if any(n.startswith("ppt/") for n in names):
                return ".pptx"
    except (zipfile.BadZipFile, Exception):
        pass
    return ".zip"


def detect_binary_extension(headers: dict[str, str], data: bytes) -> str | None:
    """Three-layer detection: CT → CD → Magic. Returns extension or None."""
    ct = headers.get("content-type") or headers.get("Content-Type") or ""
    ext = _detect_extension_from_content_type(ct)
    if ext:
        return ext

    ext = _detect_extension_from_disposition(headers)
    if ext:
        return ext

    return _detect_extension_from_magic(data)


async def route_binary_content(
    raw_body: bytes,
    headers: dict[str, str],
    url: str,
) -> Document | None:
    """Route binary content to appropriate parser and return a Document.

    Returns None if the content type is unrecognized or parsing fails.
    """
    if len(raw_body) > _MAX_BINARY_SIZE:
        logger.warning("Binary content too large (%d bytes), skipping: %s", len(raw_body), url[:100])
        return None

    ext = detect_binary_extension(headers, raw_body)
    if not ext:
        logger.info("Unrecognized binary format for %s, skipping", url[:100])
        return None

    from myrm_agent_harness.toolkits.file_parsers import is_supported

    if not is_supported(f"file{ext}"):
        logger.info("No parser available for extension %s, returning raw text", ext)
        if ext in (".zip",):
            return None
        try:
            text = raw_body.decode("utf-8", errors="replace")
            return Document(
                page_content=text[:100_000],
                metadata={"url": url, "source_type": "binary_text", "extension": ext},
            )
        except Exception:
            return None

    tmp_file = None
    try:
        tmp_file = tempfile.NamedTemporaryFile(suffix=ext, delete=False)  # noqa: SIM115  manual lifecycle: reused by path after close, removed in finally
        tmp_file.write(raw_body)
        tmp_file.flush()
        tmp_file.close()

        from myrm_agent_harness.toolkits.file_parsers import get_parser

        parser = get_parser(tmp_file.name)
        result = await parser.parse(tmp_file.name)

        if not result or not result.strip():
            return None

        return Document(
            page_content=result[:100_000],
            metadata={
                "url": url,
                "source_type": f"binary_{ext.lstrip('.')}",
                "extension": ext,
            },
        )
    except Exception as e:
        logger.warning("Failed to parse binary content from %s: %s", url[:100], e)
        return None
    finally:
        if tmp_file:
            Path(tmp_file.name).unlink(missing_ok=True)
