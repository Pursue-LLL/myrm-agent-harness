"""Content-based file format sniffing for mislabeled uploads.

[INPUT]
- File path or initial byte prefix

[OUTPUT]
- Normalized extension (e.g. ".pdf") when content signature matches

[POS]
Shared by file_parsers.get_parser and wiki/raw ingest routing.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

_MAX_SNIFF_BYTES = 8192

_ZIP_EXTENSIONS = {
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
    "application/epub+zip": ".epub",
    "application/vnd.oasis.opendocument.text": ".odt",
    "application/vnd.oasis.opendocument.spreadsheet": ".ods",
    "application/vnd.oasis.opendocument.presentation": ".odp",
}


def sniff_content_format(file_path: str | Path) -> str | None:
    """Return a supported extension inferred from file content, or None."""
    path = Path(file_path)
    if not path.is_file():
        return None

    prefix = _read_prefix(path)
    if not prefix:
        return None

    if prefix.startswith(b"%PDF"):
        return ".pdf"

    if prefix.startswith(b"{\\rtf") or prefix.startswith(b"{\\RTF"):
        return ".rtf"

    if prefix.startswith(b"PK\x03\x04"):
        return _sniff_zip_container(path)

    if prefix.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"

    if prefix[:3] == b"\xff\xd8\xff":
        return ".jpg"

    if prefix.startswith(b"RIFF") and b"WEBP" in prefix[:16]:
        return ".webp"

    if _looks_like_csv_text(prefix):
        return ".csv"

    return None


def _read_prefix(path: Path) -> bytes:
    try:
        with path.open("rb") as handle:
            return handle.read(_MAX_SNIFF_BYTES)
    except OSError:
        return b""


def _sniff_zip_container(path: Path) -> str | None:
    try:
        with zipfile.ZipFile(path) as archive:
            if "mimetype" in archive.namelist():
                raw_mimetype = (
                    archive.read("mimetype").decode("utf-8", errors="ignore").strip()
                )
                mapped = _ZIP_EXTENSIONS.get(raw_mimetype.split(";")[0].strip())
                if mapped:
                    return mapped
            if "[Content_Types].xml" in archive.namelist() and "word/" in archive.namelist()[0:20]:
                return ".docx"
            if "META-INF/container.xml" in archive.namelist():
                return ".epub"
            if "content.xml" in archive.namelist():
                return ".odt"
    except (OSError, zipfile.BadZipFile):
        return None
    return None


def sniff_content_format_from_bytes(content: bytes) -> str | None:
    """Sniff format from an in-memory byte prefix."""
    if not content:
        return None
    prefix = content[:_MAX_SNIFF_BYTES]
    if prefix.startswith(b"%PDF"):
        return ".pdf"
    if prefix.startswith(b"{\\rtf") or prefix.startswith(b"{\\RTF"):
        return ".rtf"
    if prefix.startswith(b"PK\x03\x04"):
        return _sniff_zip_container_bytes(content)
    if _looks_like_csv_text(prefix):
        return ".csv"
    return None


def _sniff_zip_container_bytes(content: bytes) -> str | None:
    import io

    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            if "mimetype" in archive.namelist():
                raw_mimetype = (
                    archive.read("mimetype").decode("utf-8", errors="ignore").strip()
                )
                mapped = _ZIP_EXTENSIONS.get(raw_mimetype.split(";")[0].strip())
                if mapped:
                    return mapped
            if "content.xml" in archive.namelist():
                return ".odt"
            if "META-INF/container.xml" in archive.namelist():
                return ".epub"
    except (OSError, zipfile.BadZipFile):
        return None
    return None


def _looks_like_csv_text(prefix: bytes) -> bool:
    try:
        sample = prefix.decode("utf-8")
    except UnicodeDecodeError:
        return False
    if "\x00" in sample:
        return False
    lines = [line for line in sample.splitlines() if line.strip()]
    if len(lines) < 2:
        return False
    comma_lines = sum(1 for line in lines[:20] if "," in line)
    return comma_lines >= 2
