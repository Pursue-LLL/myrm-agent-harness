"""Tests for PptxParser

Tests slide text, table, and speaker notes extraction from .pptx files.
"""

from __future__ import annotations

import os
import tempfile

import pytest
from pptx import Presentation
from pptx.util import Inches

from myrm_agent_harness.toolkits.file_parsers import PptxParser, get_parser, is_supported


class TestPptxParserRegistry:
    """Test parser registration and discovery."""

    def test_pptx_is_supported(self) -> None:
        assert is_supported("slides.pptx") is True

    def test_ppt_is_supported(self) -> None:
        assert is_supported("old.ppt") is True

    def test_get_parser_returns_pptx_parser(self) -> None:
        parser = get_parser("report.pptx")
        assert isinstance(parser, PptxParser)

    def test_supported_extensions(self) -> None:
        parser = PptxParser()
        assert ".pptx" in parser.supported_extensions
        assert ".ppt" in parser.supported_extensions


class TestPptxParserBasic:
    """Test basic slide text extraction."""

    @pytest.mark.asyncio
    async def test_single_slide_text(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".pptx", delete=False) as f:
            prs = Presentation()
            slide = prs.slides.add_slide(prs.slide_layouts[0])
            slide.shapes.title.text = "Hello World"
            slide.placeholders[1].text = "Body content here"
            prs.save(f.name)
            tmp = f.name

        try:
            parser = PptxParser()
            result = await parser.parse(tmp)
            assert "## Slide 1" in result
            assert "Hello World" in result
            assert "Body content here" in result
        finally:
            os.unlink(tmp)

    @pytest.mark.asyncio
    async def test_multiple_slides(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".pptx", delete=False) as f:
            prs = Presentation()
            for i in range(3):
                slide = prs.slides.add_slide(prs.slide_layouts[0])
                slide.shapes.title.text = f"Slide {i + 1} Title"
                slide.placeholders[1].text = f"Content {i + 1}"
            prs.save(f.name)
            tmp = f.name

        try:
            parser = PptxParser()
            result = await parser.parse(tmp)
            assert "## Slide 1" in result
            assert "## Slide 2" in result
            assert "## Slide 3" in result
            assert "Slide 1 Title" in result
            assert "Content 3" in result
            assert "---" in result
        finally:
            os.unlink(tmp)

    @pytest.mark.asyncio
    async def test_empty_presentation(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".pptx", delete=False) as f:
            prs = Presentation()
            prs.save(f.name)
            tmp = f.name

        try:
            parser = PptxParser()
            result = await parser.parse(tmp)
            assert result == "(Empty presentation)"
        finally:
            os.unlink(tmp)

    @pytest.mark.asyncio
    async def test_file_not_found(self) -> None:
        parser = PptxParser()
        with pytest.raises(FileNotFoundError):
            await parser.parse("/nonexistent/path.pptx")


class TestPptxParserTable:
    """Test table extraction."""

    @pytest.mark.asyncio
    async def test_table_extraction(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".pptx", delete=False) as f:
            prs = Presentation()
            slide = prs.slides.add_slide(prs.slide_layouts[5])  # blank layout
            table = slide.shapes.add_table(3, 2, Inches(1), Inches(1), Inches(4), Inches(2)).table
            table.cell(0, 0).text = "Name"
            table.cell(0, 1).text = "Score"
            table.cell(1, 0).text = "Alice"
            table.cell(1, 1).text = "95"
            table.cell(2, 0).text = "Bob"
            table.cell(2, 1).text = "88"
            prs.save(f.name)
            tmp = f.name

        try:
            parser = PptxParser()
            result = await parser.parse(tmp)
            assert "| Name | Score |" in result
            assert "| --- | --- |" in result
            assert "| Alice | 95 |" in result
            assert "| Bob | 88 |" in result
        finally:
            os.unlink(tmp)


class TestPptxParserNotes:
    """Test speaker notes extraction."""

    @pytest.mark.asyncio
    async def test_notes_extraction(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".pptx", delete=False) as f:
            prs = Presentation()
            slide = prs.slides.add_slide(prs.slide_layouts[0])
            slide.shapes.title.text = "Slide with Notes"
            slide.placeholders[1].text = "Main content"
            notes_slide = slide.notes_slide
            notes_slide.notes_text_frame.text = "Remember to mention the Q2 numbers"
            prs.save(f.name)
            tmp = f.name

        try:
            parser = PptxParser()
            result = await parser.parse(tmp)
            assert "Remember to mention the Q2 numbers" in result
            assert "> **Notes:**" in result
        finally:
            os.unlink(tmp)


class TestPptxParserSync:
    """Test _parse_sync directly for mention.py integration."""

    def test_parse_sync_works(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".pptx", delete=False) as f:
            prs = Presentation()
            slide = prs.slides.add_slide(prs.slide_layouts[0])
            slide.shapes.title.text = "Sync Test"
            prs.save(f.name)
            tmp = f.name

        try:
            parser = PptxParser()
            result = parser._parse_sync(tmp)
            assert "Sync Test" in result
        finally:
            os.unlink(tmp)
