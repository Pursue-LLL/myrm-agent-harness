"""Store clip/upload assets under wiki/assets/ with content-hash deduplication.

[INPUT]
- core.structure.WikiStructure (POS: vault directory layout)
- core.security.http.secure_fetch (POS: server-side public asset fetch)

[OUTPUT]
- store_clip_assets / localize_public_markdown_images / rewrite_markdown_asset_refs

[POS] Clip and URL-ingest asset localization into wiki/assets/.
"""

from __future__ import annotations

import hashlib
import logging
import mimetypes
import re
from pathlib import Path
from urllib.parse import urlparse

from myrm_agent_harness.core.security.http.secure_fetch import secure_get
from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure

from .types import ClipAssetInput, IngressAssetStats

logger = logging.getLogger(__name__)

_MAX_CLIP_ASSETS = 20
_MAX_ASSET_BYTES = 5 * 1024 * 1024
_MARKDOWN_IMAGE_RE = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")

_CONTENT_TYPE_EXT: dict[str, str] = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/svg+xml": ".svg",
}


def _extension_for(content_type: str, data: bytes) -> str:
    ct = content_type.split(";", 1)[0].strip().lower()
    if ct in _CONTENT_TYPE_EXT:
        return _CONTENT_TYPE_EXT[ct]
    guessed = mimetypes.guess_extension(ct)
    if guessed:
        return guessed
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    if data[:3] == b"\xff\xd8\xff":
        return ".jpg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return ".gif"
    return ".bin"


def _asset_relpath_from_raw(raw_relative: str, asset_filename: str) -> str:
    raw_parts = len(Path(raw_relative).parent.parts)
    ups = [".."] * (raw_parts + 1)
    return "/".join([*ups, "wiki", "assets", asset_filename])


def store_asset_bytes(
    structure: WikiStructure,
    *,
    data: bytes,
    content_type: str,
) -> str | None:
    if not data or len(data) > _MAX_ASSET_BYTES:
        return None
    structure.ensure_structure()
    digest = hashlib.sha256(data).hexdigest()
    ext = _extension_for(content_type, data)
    filename = f"{digest}{ext}"
    dest = structure.wiki_dir / "assets" / filename
    if not dest.exists():
        dest.write_bytes(data)
    return filename


def store_clip_assets(
    structure: WikiStructure,
    assets: tuple[ClipAssetInput, ...],
) -> tuple[dict[str, str], IngressAssetStats]:
    """Map source_url -> asset filename (wiki/assets/{hash}.ext)."""
    url_to_filename: dict[str, str] = {}
    stored = 0
    skipped = 0
    failed = 0
    for item in assets[:_MAX_CLIP_ASSETS]:
        filename = store_asset_bytes(
            structure, data=item.data, content_type=item.content_type
        )
        if filename is None:
            failed += 1
            continue
        if item.source_url in url_to_filename:
            skipped += 1
            continue
        url_to_filename[item.source_url] = filename
        stored += 1
    return url_to_filename, IngressAssetStats(stored=stored, skipped=skipped, failed=failed)


async def localize_public_markdown_images(
    structure: WikiStructure,
    markdown: str,
    *,
    base_url: str,
) -> tuple[str, IngressAssetStats]:
    """Download public http(s) images referenced in markdown (server-side Track B)."""
    url_to_filename: dict[str, str] = {}
    stored = 0
    skipped = 0
    failed = 0
    seen: set[str] = set()
    for match in _MARKDOWN_IMAGE_RE.finditer(markdown):
        raw_ref = match.group(1).strip().split(" ", 1)[0]
        if raw_ref.startswith("data:") or raw_ref in seen:
            continue
        seen.add(raw_ref)
        if len(url_to_filename) >= _MAX_CLIP_ASSETS:
            break
        resolved = raw_ref
        if not raw_ref.startswith(("http://", "https://")):
            if base_url:
                from urllib.parse import urljoin

                resolved = urljoin(base_url, raw_ref)
            else:
                continue
        parsed = urlparse(resolved)
        if parsed.scheme not in {"http", "https"}:
            continue
        try:
            response = await secure_get(resolved, timeout=20.0)
            if response.status_code != 200:
                failed += 1
                continue
            content_type = response.headers.get("content-type", "application/octet-stream")
            data = response.content
            filename = store_asset_bytes(
                structure, data=data, content_type=content_type
            )
            if filename is None:
                failed += 1
                continue
            url_to_filename[raw_ref] = filename
            if resolved != raw_ref:
                url_to_filename[resolved] = filename
            stored += 1
        except Exception as exc:
            logger.debug("Asset fetch failed for %s: %s", resolved[:120], exc)
            failed += 1
    if not url_to_filename:
        return markdown, IngressAssetStats(stored=0, skipped=0, failed=failed)
    rewritten = rewrite_markdown_asset_refs(markdown, url_to_filename, raw_relative="placeholder.md")
    return rewritten, IngressAssetStats(stored=stored, skipped=skipped, failed=failed)


def rewrite_markdown_asset_refs(
    markdown: str,
    url_to_filename: dict[str, str],
    *,
    raw_relative: str,
) -> str:
    if not url_to_filename:
        return markdown

    def _replace(match: re.Match[str]) -> str:
        full = match.group(0)
        alt_match = re.match(r"!\[(.*?)\]", full)
        alt = alt_match.group(1) if alt_match else ""
        ref = match.group(1).strip().split(" ", 1)[0]
        filename = url_to_filename.get(ref)
        if not filename:
            return full
        rel = _asset_relpath_from_raw(raw_relative, filename)
        return f"![{alt}]({rel})"

    return _MARKDOWN_IMAGE_RE.sub(_replace, markdown)
