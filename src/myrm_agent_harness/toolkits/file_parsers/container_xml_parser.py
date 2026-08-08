"""EPUB and ODF container parsers (zip + XML text extraction)."""

from __future__ import annotations

import logging
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree

from myrm_agent_harness.toolkits.file_parsers.base import FileParser

logger = logging.getLogger(__name__)

_TAG_RE = re.compile(r"<[^>]+>")


class EpubParser(FileParser):
    """Extract plain text from EPUB XHTML items."""

    async def parse(self, file_path: str) -> str:
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        chunks: list[str] = []
        with zipfile.ZipFile(path) as archive:
            for name in sorted(archive.namelist()):
                if not (name.endswith(".xhtml") or name.endswith(".html")):
                    continue
                raw = archive.read(name).decode("utf-8", errors="ignore")
                text = _TAG_RE.sub(" ", raw)
                normalized = " ".join(text.split())
                if normalized:
                    chunks.append(normalized)

        joined = "\n\n".join(chunks)
        logger.info("EPUB parsed: %s, sections=%d", path.name, len(chunks))
        return joined

    @property
    def supported_extensions(self) -> list[str]:
        return [".epub"]


class OdfParser(FileParser):
    """Extract text from OpenDocument ZIP packages."""

    def __init__(self, extension: str) -> None:
        self._extension = extension

    async def parse(self, file_path: str) -> str:
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        with zipfile.ZipFile(path) as archive:
            if "content.xml" not in archive.namelist():
                return ""
            raw_xml = archive.read("content.xml")

        root = ElementTree.fromstring(raw_xml)  # noqa: S314  # expat blocks external entities by default
        texts = [
            node.text.strip() for node in root.iter() if node.text and node.text.strip()
        ]
        joined = "\n".join(texts)
        logger.info("ODF parsed: %s, nodes=%d", path.name, len(texts))
        return joined

    @property
    def supported_extensions(self) -> list[str]:
        return [self._extension]
