"""Wiki clip + URL markdown ingress SSOT → publish_raw.

[INPUT]
- pipeline.raw_gate (POS: raw publication gate)
- toolkits.web_fetch (POS: HTML→markdown pruning)
- ingress.asset_store (POS: wiki/assets hash store)

[OUTPUT]
- publish_clip_ingress / publish_url_markdown_ingress (POS: clip + URL ingress writers)

[POS] Wiki raw ingress writers. Normalize clip/URL content then call publish_raw.
"""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from myrm_agent_harness.toolkits.web_fetch.content_pruning import ContentPruningFilter
from myrm_agent_harness.toolkits.web_fetch.markdown_generator import MarkdownGenerator
from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure
from myrm_agent_harness.toolkits.wiki.pipeline.raw_gate import (
    RawConflictPolicy,
    RawGateError,
    RawPublishRequest,
    publish_raw,
)

from .asset_store import (
    localize_public_markdown_images,
    rewrite_markdown_asset_refs,
    store_clip_assets,
)
from .types import (
    ClipIngressRequest,
    ClipIngressResult,
    ClipMode,
    IngressAssetStats,
    UrlMarkdownIngressRequest,
)

_TITLE_SLUG_RE = re.compile(r"[^\w\s-]", re.UNICODE)


def _slugify_title(title: str, *, max_len: int = 60) -> str:
    cleaned = _TITLE_SLUG_RE.sub("", title.lower())
    cleaned = re.sub(r"[\s_]+", "-", cleaned).strip("-")
    if not cleaned:
        cleaned = "clip"
    return cleaned[:max_len] or "clip"


def _default_clip_path(title: str, source_url: str) -> str:
    month = datetime.now(UTC).strftime("%Y-%m")
    slug = _slugify_title(title)
    if not slug or slug == "clip":
        slug = f"web_{hashlib.sha256(source_url.encode()).hexdigest()[:10]}"
    return f"clips/{month}/{slug}.md"


def _build_frontmatter(
    *,
    source_url: str,
    title: str,
    clip_mode: ClipMode | None,
    assets_localized: str,
) -> str:
    lines = [
        "---",
        f'source_url: "{source_url.replace(chr(34), "")}"',
        f'title: "{title.replace(chr(34), "")}"',
        f"clipped_at: {datetime.now(UTC).isoformat()}",
    ]
    if clip_mode is not None:
        lines.append(f"clip_mode: {clip_mode.value}")
    lines.append(f"assets_localized: {assets_localized}")
    lines.append("---")
    return "\n".join(lines) + "\n\n"


def _html_to_markdown(html: str, *, base_url: str) -> str:
    if not html.strip():
        return ""
    pruner = ContentPruningFilter()
    generator = MarkdownGenerator(content_filter=pruner)
    result = generator.generate_markdown(html, base_url=base_url, citations=False)
    return (result.raw_markdown or "").strip()


def _resolve_relative_path(request: ClipIngressRequest) -> str:
    if request.folder_path.strip():
        folder = WikiStructure._sanitize_path(request.folder_path.strip())
        slug = _slugify_title(request.title)
        return f"{folder}/{slug}.md"
    return _default_clip_path(request.title, request.source_url)


def _assets_localized_label(
    asset_stats: IngressAssetStats,
    *,
    had_markdown_refs: bool,
) -> Literal["full", "partial", "remote"]:
    if asset_stats.stored == 0 and not had_markdown_refs:
        return "remote"
    if asset_stats.failed > 0:
        return "partial"
    return "full"


async def publish_clip_ingress(
    structure: WikiStructure,
    request: ClipIngressRequest,
) -> ClipIngressResult:
    structure.ensure_structure()
    rel_path = _resolve_relative_path(request)

    body = request.markdown.strip()
    if not body and request.html.strip():
        body = _html_to_markdown(request.html, base_url=request.source_url)
    if not body:
        body = f"# {request.title or 'Untitled'}\n\n(source: {request.source_url})"

    url_map, asset_stats = store_clip_assets(structure, request.assets)
    had_refs = bool(re.search(r"!\[[^\]]*\]\(", body))
    if url_map:
        body = rewrite_markdown_asset_refs(body, url_map, raw_relative=rel_path)

    localized = _assets_localized_label(asset_stats, had_markdown_refs=had_refs)
    content = _build_frontmatter(
        source_url=request.source_url,
        title=request.title,
        clip_mode=request.clip_mode,
        assets_localized=localized,
    ) + body

    try:
        result = await publish_raw(
            structure,
            RawPublishRequest(
                relative_path=rel_path,
                content=content,
                conflict_policy=RawConflictPolicy.FAIL,
            ),
            caller="extension",
        )
    except RawGateError as exc:
        if exc.code == "raw_conflict":
            return ClipIngressResult(
                relative_path=rel_path,
                written=False,
                skipped=True,
                conflict=True,
                security_blocked=False,
                assets_localized=localized,
                asset_stats=asset_stats,
            )
        if exc.code == "raw_security_blocked":
            return ClipIngressResult(
                relative_path=rel_path,
                written=False,
                skipped=False,
                conflict=False,
                security_blocked=True,
                assets_localized=localized,
                asset_stats=asset_stats,
            )
        raise

    return ClipIngressResult(
        relative_path=rel_path,
        written=result.written,
        skipped=result.skipped,
        conflict=result.conflict_skipped,
        security_blocked=result.security_blocked,
        assets_localized=localized,
        asset_stats=asset_stats,
    )


async def publish_url_markdown_ingress(
    structure: WikiStructure,
    request: UrlMarkdownIngressRequest,
    *,
    markdown: str,
) -> ClipIngressResult:
    structure.ensure_structure()
    if request.relative_path.strip():
        rel_path = request.relative_path.strip().replace("\\", "/").lstrip("/")
    else:
        filename = request.filename.strip()
        if not filename:
            filename = f"web_{hashlib.sha256(request.url.encode()).hexdigest()[:12]}.md"
        if not filename.endswith(".md"):
            filename = f"{filename}.md"
        if request.folder_path.strip():
            folder = WikiStructure._sanitize_path(request.folder_path.strip())
            rel_path = f"{folder}/{Path(filename).name}"
        else:
            rel_path = Path(filename).name

    body = markdown
    asset_stats = IngressAssetStats()
    localized: Literal["full", "partial", "remote"] = "remote"
    if request.localize_public_assets:
        body, asset_stats = await localize_public_markdown_images(
            structure, body, base_url=request.url
        )
        localized = _assets_localized_label(
            asset_stats, had_markdown_refs=bool(re.search(r"!\[[^\]]*\]\(", markdown))
        )

    title = Path(rel_path).stem
    content = _build_frontmatter(
        source_url=request.url,
        title=title,
        clip_mode=None,
        assets_localized=localized,
    ) + body

    try:
        result = await publish_raw(
            structure,
            RawPublishRequest(
                relative_path=rel_path,
                content=content,
                conflict_policy=RawConflictPolicy.FAIL,
            ),
            caller="agent",
        )
    except RawGateError as exc:
        if exc.code == "raw_conflict":
            return ClipIngressResult(
                relative_path=rel_path,
                written=False,
                skipped=True,
                conflict=True,
                security_blocked=False,
                assets_localized=localized,
                asset_stats=asset_stats,
            )
        if exc.code == "raw_security_blocked":
            return ClipIngressResult(
                relative_path=rel_path,
                written=False,
                skipped=False,
                conflict=False,
                security_blocked=True,
                assets_localized=localized,
                asset_stats=asset_stats,
            )
        raise

    return ClipIngressResult(
        relative_path=rel_path,
        written=result.written,
        skipped=result.skipped,
        conflict=result.conflict_skipped,
        security_blocked=result.security_blocked,
        assets_localized=localized,
        asset_stats=asset_stats,
    )
