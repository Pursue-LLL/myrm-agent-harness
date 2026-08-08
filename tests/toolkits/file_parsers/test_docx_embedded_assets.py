"""Tests for DOCX embedded image extraction and asset localization."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from myrm_agent_harness.toolkits.file_parsers.docx import DocxParser
from myrm_agent_harness.toolkits.file_parsers.docx_embedded_assets import (
    extract_docx_embedded_images,
    localize_docx_embedded_markdown,
)
from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure


def _write_min_docx_with_png(target: Path, png_bytes: bytes) -> None:
    document_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"
            xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
            xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
            xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
            xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture">
  <w:body>
    <w:p><w:r><w:t>Fixture doc</w:t></w:r></w:p>
    <w:p>
      <w:r>
        <w:drawing>
          <wp:inline>
            <wp:extent cx="1000000" cy="1000000"/>
            <a:graphic>
              <a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">
                <pic:pic>
                  <pic:blipFill>
                    <a:blip r:embed="rId5"/>
                  </pic:blipFill>
                </pic:pic>
              </a:graphicData>
            </a:graphic>
          </wp:inline>
        </w:drawing>
      </w:r>
    </w:p>
  </w:body>
</w:document>"""
    rels_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId5"
    Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image"
    Target="media/image1.png"/>
</Relationships>"""
    content_types = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="png" ContentType="image/png"/>
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml"
    ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>"""
    root_rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1"
    Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument"
    Target="word/document.xml"/>
</Relationships>"""
    with zipfile.ZipFile(target, "w") as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", root_rels)
        archive.writestr("word/document.xml", document_xml)
        archive.writestr("word/_rels/document.xml.rels", rels_xml)
        archive.writestr("word/media/image1.png", png_bytes)


@pytest.mark.asyncio
async def test_docx_parser_emits_embed_markdown_ref(tmp_path: Path) -> None:
    png_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
    docx_path = tmp_path / "fixture.docx"
    _write_min_docx_with_png(docx_path, png_bytes)

    parser = DocxParser()
    text = await parser.parse(str(docx_path))
    assert "Fixture doc" in text
    assert "docx-embed:rId5" in text

    images = extract_docx_embedded_images(docx_path)
    assert "rId5" in images
    assert images["rId5"].data == png_bytes


def test_localize_docx_embedded_markdown_writes_assets(tmp_path: Path) -> None:
    png_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
    docx_path = tmp_path / "fixture.docx"
    _write_min_docx_with_png(docx_path, png_bytes)
    images = extract_docx_embedded_images(docx_path)

    structure = WikiStructure(tmp_path / "wiki")
    structure.ensure_structure()
    from myrm_agent_harness.toolkits.wiki.pipeline.ingress.asset_store import (
        store_asset_bytes,
    )

    markdown = "![embedded image](docx-embed:rId5)"
    localized = localize_docx_embedded_markdown(
        markdown,
        images,
        store_asset=lambda data, content_type: store_asset_bytes(
            structure,
            data=data,
            content_type=content_type,
        ),
        raw_relative="gdrive/2026-08/sample.md",
    )
    assert "wiki/assets/" in localized
    assert (structure.wiki_dir / "assets").exists()
    assert any((structure.wiki_dir / "assets").iterdir())
