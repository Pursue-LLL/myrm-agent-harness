"""Wiki ingress pipeline tests (clip, wikiignore, assets)."""

from __future__ import annotations

import pytest

from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure
from myrm_agent_harness.toolkits.wiki.pipeline.ingress.asset_store import (
    rewrite_markdown_asset_refs,
    store_asset_bytes,
    store_clip_assets,
)
from myrm_agent_harness.toolkits.wiki.pipeline.ingress.publish import publish_clip_ingress
from myrm_agent_harness.toolkits.wiki.pipeline.ingress.types import (
    ClipAssetInput,
    ClipIngressRequest,
    ClipMode,
)
from myrm_agent_harness.toolkits.wiki.pipeline.ingress.wikiignore import (
    load_wikiignore_patterns,
    path_matches_wikiignore,
    write_wikiignore_patterns,
)


@pytest.fixture
def temp_structure(tmp_path) -> WikiStructure:
    structure = WikiStructure(base_dir=tmp_path)
    structure.ensure_structure()
    return structure


def test_path_matches_wikiignore_patterns() -> None:
    patterns = ("drafts/**", "*.tmp", "secret.md")
    assert path_matches_wikiignore("drafts/note.md", patterns)
    assert path_matches_wikiignore("folder/file.tmp", patterns)
    assert path_matches_wikiignore("secret.md", patterns)
    assert not path_matches_wikiignore("notes/ok.md", patterns)


def test_load_and_write_wikiignore(temp_structure: WikiStructure) -> None:
    write_wikiignore_patterns(temp_structure, "drafts/**\n# comment\n*.bak\n")
    loaded = load_wikiignore_patterns(temp_structure)
    assert loaded == ("drafts/**", "*.bak")


def test_scan_folder_respects_wikiignore(temp_structure: WikiStructure, tmp_path) -> None:
    source = tmp_path / "import-src"
    (source / "keep").mkdir(parents=True)
    (source / "drafts").mkdir()
    (source / "keep" / "a.md").write_text("keep", encoding="utf-8")
    (source / "drafts" / "b.md").write_text("skip", encoding="utf-8")

    write_wikiignore_patterns(temp_structure, "drafts/**\n")
    files = temp_structure.scan_folder(source, extensions=[".md"])
    rel_paths = {f.relative_to(source).as_posix() for f in files}
    assert rel_paths == {"keep/a.md"}


def test_store_clip_assets_dedupes_by_url(temp_structure: WikiStructure) -> None:
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
    assets = (
        ClipAssetInput(source_url="https://example.com/a.png", content_type="image/png", data=png),
        ClipAssetInput(source_url="https://example.com/a.png", content_type="image/png", data=png),
    )
    url_map, stats = store_clip_assets(temp_structure, assets)
    assert len(url_map) == 1
    assert stats.stored == 1
    assert stats.skipped == 1


def test_rewrite_markdown_asset_refs(temp_structure: WikiStructure) -> None:
    filename = store_asset_bytes(temp_structure, data=b"img", content_type="image/png")
    assert filename is not None
    md = "![alt](https://example.com/img.png)"
    rewritten = rewrite_markdown_asset_refs(
        md,
        {"https://example.com/img.png": filename},
        raw_relative="clips/2026-08/demo.md",
    )
    assert filename in rewritten
    assert "https://example.com" not in rewritten


@pytest.mark.asyncio
async def test_publish_clip_ingress_writes_raw(temp_structure: WikiStructure) -> None:
    result = await publish_clip_ingress(
        temp_structure,
        ClipIngressRequest(
            source_url="https://example.com/post",
            title="Demo Post",
            clip_mode=ClipMode.FULL_PAGE,
            markdown="# Demo\n\nBody text.",
        ),
    )
    assert result.written is True
    assert result.conflict is False
    raw_path = temp_structure.get_raw_file_path(result.relative_path)
    assert raw_path.is_file()
    content = raw_path.read_text(encoding="utf-8")
    assert "source_url:" in content
    assert "clip_mode: full_page" in content
    assert "# Demo" in content


@pytest.mark.asyncio
async def test_publish_url_markdown_ingress_writes_raw(temp_structure: WikiStructure) -> None:
    from myrm_agent_harness.toolkits.wiki.pipeline.ingress.types import (
        UrlMarkdownIngressRequest,
    )
    from myrm_agent_harness.toolkits.wiki.pipeline.ingress.publish import (
        publish_url_markdown_ingress,
    )

    result = await publish_url_markdown_ingress(
        temp_structure,
        UrlMarkdownIngressRequest(url="https://example.com/doc"),
        markdown="# Doc\n\nFrom URL ingress.",
    )
    assert result.written is True
    raw_path = temp_structure.get_raw_file_path(result.relative_path)
    assert raw_path.is_file()
    text = raw_path.read_text(encoding="utf-8")
    assert "source_url:" in text
    assert "From URL ingress." in text


@pytest.mark.asyncio
async def test_publish_clip_ingress_conflict_skips(temp_structure: WikiStructure) -> None:
    rel = "clips/manual/existing.md"
    existing = temp_structure.get_raw_file_path(rel)
    existing.parent.mkdir(parents=True, exist_ok=True)
    existing.write_text("existing", encoding="utf-8")

    result = await publish_clip_ingress(
        temp_structure,
        ClipIngressRequest(
            source_url="https://example.com/x",
            title="Existing",
            clip_mode=ClipMode.SELECTION,
            markdown="# New",
            folder_path="clips/manual",
        ),
    )
    assert result.written is False
    assert result.conflict is True
    assert existing.read_text(encoding="utf-8") == "existing"
