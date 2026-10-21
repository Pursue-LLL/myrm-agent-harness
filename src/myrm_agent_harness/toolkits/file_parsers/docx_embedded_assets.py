"""Extract embedded images from DOCX packages and localize markdown refs.

[INPUT]
- myrm_agent_harness.toolkits.wiki.pipeline.ingress.asset_store (POS: asset persistence)

[OUTPUT]
- extract_docx_embedded_images / find_docx_embed_ids / localize_docx_embedded_markdown

[POS]
DOCX OOXML relationship-id → image bytes extractor and markdown ref localizer.
"""

from __future__ import annotations

import mimetypes
import xml.etree.ElementTree as ET
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

_DOCX_EMBED_PREFIX = "docx-embed:"
_IMAGE_REL_TYPE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image"
_EMBED_ATTR = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed"

StoreAsset = Callable[[bytes, str], str | None]


@dataclass(frozen=True, slots=True)
class DocxEmbeddedImage:
    """Single embedded image payload keyed by OOXML relationship id (rIdN)."""

    embed_id: str
    data: bytes
    mime_type: str
    media_path: str


def extract_docx_embedded_images(file_path: str | Path) -> dict[str, DocxEmbeddedImage]:
    """Return relationship-id → image bytes map from a DOCX archive."""
    path = Path(file_path)
    if not path.is_file():
        return {}

    rel_targets: dict[str, str] = {}
    images: dict[str, DocxEmbeddedImage] = {}

    try:
        with zipfile.ZipFile(path) as archive:
            rels_path = "word/_rels/document.xml.rels"
            if rels_path not in archive.namelist():
                return {}
            rel_root = ET.fromstring(  # noqa: S314 — expat blocks external entities by default
                archive.read(rels_path)
            )
            for rel in rel_root:
                rel_id = rel.get("Id")
                rel_type = rel.get("Type", "")
                target = rel.get("Target", "")
                if not rel_id or rel_type != _IMAGE_REL_TYPE or not target:
                    continue
                media_path = target if target.startswith("word/") else f"word/{target.lstrip('/')}"
                rel_targets[rel_id] = media_path

            for embed_id, media_path in rel_targets.items():
                if media_path not in archive.namelist():
                    continue
                data = archive.read(media_path)
                if not data:
                    continue
                mime_type = _guess_mime_type(media_path, data)
                images[embed_id] = DocxEmbeddedImage(
                    embed_id=embed_id,
                    data=data,
                    mime_type=mime_type,
                    media_path=media_path,
                )
    except (OSError, zipfile.BadZipFile, ET.ParseError):
        return {}

    return images


def docx_embed_markdown_ref(embed_id: str) -> str:
    return f"{_DOCX_EMBED_PREFIX}{embed_id}"


def find_docx_embed_ids(element: ET.Element) -> list[str]:
    """Collect r:embed ids from a paragraph/table OOXML element subtree."""
    ids: list[str] = []
    seen: set[str] = set()
    for node in element.iter():
        if not node.tag.endswith("}blip"):
            continue
        embed = node.get(_EMBED_ATTR)
        if embed and embed not in seen:
            seen.add(embed)
            ids.append(embed)
    return ids


def localize_docx_embedded_markdown(
    markdown: str,
    images: dict[str, DocxEmbeddedImage],
    *,
    store_asset: StoreAsset,
    raw_relative: str,
) -> str:
    """Rewrite ``docx-embed:rIdN`` refs to ``../wiki/assets/{hash}.ext`` paths."""
    if not images or not markdown:
        return markdown

    from myrm_agent_harness.toolkits.wiki.pipeline.ingress.asset_store import (
        rewrite_markdown_asset_refs,
    )

    ref_to_filename: dict[str, str] = {}
    for embed_id, image in images.items():
        filename = store_asset(data=image.data, content_type=image.mime_type)
        if filename:
            ref_to_filename[docx_embed_markdown_ref(embed_id)] = filename

    if not ref_to_filename:
        return markdown

    return rewrite_markdown_asset_refs(
        markdown,
        ref_to_filename,
        raw_relative=raw_relative,
    )


def _guess_mime_type(media_path: str, data: bytes) -> str:
    guessed, _ = mimetypes.guess_type(media_path)
    if guessed:
        return guessed
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    return "application/octet-stream"
