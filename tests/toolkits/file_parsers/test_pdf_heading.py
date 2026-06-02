"""Unit tests for font-based heading detection in PDF files."""

from unittest.mock import Mock, PropertyMock

import pytest

from myrm_agent_harness.toolkits.file_parsers.pdf_heading import (
    DetectedHeading,
    FontHeadingConfig,
    _compute_heading_sizes,
    _deduplicate_headers,
    _extract_heading_text,
    detect_headings_by_font,
)


def _make_char(text: str, size: float, top: float, x0: float = 0.0) -> dict:
    """Helper to create a mock character dict."""
    return {"text": text, "size": size, "top": top, "x0": x0}


def _make_page(chars: list[dict], page_number: int = 1) -> Mock:
    """Helper to create a mock pdfplumber page."""
    page = Mock()
    page.chars = chars
    page.page_number = page_number
    return page


class TestComputeHeadingSizes:
    """Test font size analysis and heading level computation."""

    def test_identifies_heading_sizes(self):
        """Body text at 10pt, headings at 14pt and 12pt."""
        body_chars = [_make_char("x", 10.0, i) for i in range(100)]
        h1_chars = [_make_char("H", 14.0, 200 + i) for i in range(5)]
        h2_chars = [_make_char("S", 12.0, 300 + i) for i in range(10)]

        page = _make_page(body_chars + h1_chars + h2_chars)
        pdf = Mock()
        pdf.pages = [page]

        cfg = FontHeadingConfig(min_delta=1.5, sample_interval=1)
        result = _compute_heading_sizes(pdf, cfg)

        assert 14.0 in result
        assert 12.0 in result
        assert result[14.0] == 1  # Largest = level 1
        assert result[12.0] == 2  # Smaller = level 2

    def test_no_headings_when_uniform_font(self):
        """All text at same size returns empty."""
        chars = [_make_char("x", 10.0, i) for i in range(50)]
        page = _make_page(chars)
        pdf = Mock()
        pdf.pages = [page]

        cfg = FontHeadingConfig(sample_interval=1)
        result = _compute_heading_sizes(pdf, cfg)
        assert result == {}

    def test_respects_max_levels(self):
        """Limits detected levels to max_levels."""
        body_chars = [_make_char("x", 10.0, i) for i in range(100)]
        sizes = [18.0, 16.0, 14.0, 12.0, 11.5]
        extra_chars = []
        for s in sizes:
            extra_chars.extend([_make_char("H", s, 500 + i) for i in range(3)])

        page = _make_page(body_chars + extra_chars)
        pdf = Mock()
        pdf.pages = [page]

        cfg = FontHeadingConfig(min_delta=1.0, max_levels=3, sample_interval=1)
        result = _compute_heading_sizes(pdf, cfg)

        assert len(result) <= 3

    def test_empty_pdf(self):
        """Empty PDF returns empty."""
        pdf = Mock()
        pdf.pages = []

        cfg = FontHeadingConfig(sample_interval=1)
        result = _compute_heading_sizes(pdf, cfg)
        assert result == {}


class TestExtractHeadingText:
    """Test heading text extraction from pages."""

    def test_extracts_heading_text(self):
        """Extracts text matching heading sizes."""
        chars = [
            _make_char("T", 14.0, 10.0, 0.0),
            _make_char("i", 14.0, 10.0, 5.0),
            _make_char("t", 14.0, 10.0, 10.0),
            _make_char("l", 14.0, 10.0, 15.0),
            _make_char("e", 14.0, 10.0, 20.0),
            _make_char("b", 10.0, 30.0, 0.0),
            _make_char("o", 10.0, 30.0, 5.0),
            _make_char("d", 10.0, 30.0, 10.0),
            _make_char("y", 10.0, 30.0, 15.0),
        ]
        page = _make_page(chars, page_number=1)
        pdf = Mock()
        pdf.pages = [page]

        size_to_level = {14.0: 1}
        cfg = FontHeadingConfig()
        result = _extract_heading_text(pdf, size_to_level, cfg)

        assert len(result) == 1
        assert result[0].title == "Title"
        assert result[0].level == 1
        assert result[0].page_num == 1

    def test_filters_short_titles(self):
        """Titles shorter than min_title_length are excluded."""
        chars = [_make_char("A", 14.0, 10.0)]
        page = _make_page(chars, page_number=1)
        pdf = Mock()
        pdf.pages = [page]

        size_to_level = {14.0: 1}
        cfg = FontHeadingConfig(min_title_length=2)
        result = _extract_heading_text(pdf, size_to_level, cfg)

        assert len(result) == 0

    def test_filters_numeric_only_titles(self):
        """Digit-only titles (page numbers) are excluded."""
        chars = [
            _make_char("1", 14.0, 10.0, 0.0),
            _make_char("2", 14.0, 10.0, 5.0),
            _make_char("3", 14.0, 10.0, 10.0),
        ]
        page = _make_page(chars, page_number=1)
        pdf = Mock()
        pdf.pages = [page]

        size_to_level = {14.0: 1}
        cfg = FontHeadingConfig()
        result = _extract_heading_text(pdf, size_to_level, cfg)

        assert len(result) == 0

    def test_multi_line_headings_split_correctly(self):
        """Lines at different vertical positions become separate headings."""
        chars = [
            _make_char("A", 14.0, 10.0, 0.0),
            _make_char("B", 14.0, 10.0, 5.0),
            _make_char("C", 14.0, 50.0, 0.0),
            _make_char("D", 14.0, 50.0, 5.0),
        ]
        page = _make_page(chars, page_number=1)
        pdf = Mock()
        pdf.pages = [page]

        size_to_level = {14.0: 1}
        cfg = FontHeadingConfig()
        result = _extract_heading_text(pdf, size_to_level, cfg)

        assert len(result) == 2
        assert result[0].title == "AB"
        assert result[1].title == "CD"

    def test_filters_too_long_titles(self):
        """Titles exceeding max_title_length are excluded."""
        long_text = "A" * 130
        chars = [_make_char(c, 14.0, 10.0, i * 5.0) for i, c in enumerate(long_text)]
        page = _make_page(chars, page_number=1)
        pdf = Mock()
        pdf.pages = [page]

        size_to_level = {14.0: 1}
        cfg = FontHeadingConfig(max_title_length=120)
        result = _extract_heading_text(pdf, size_to_level, cfg)

        assert len(result) == 0

    def test_filters_noise_pattern_titles(self):
        """Titles matching noise pattern (dots, dashes) are excluded."""
        noise = "1.2.3..."
        chars = [_make_char(c, 14.0, 10.0, i * 5.0) for i, c in enumerate(noise)]
        page = _make_page(chars, page_number=1)
        pdf = Mock()
        pdf.pages = [page]

        size_to_level = {14.0: 1}
        cfg = FontHeadingConfig()
        result = _extract_heading_text(pdf, size_to_level, cfg)

        assert len(result) == 0

    def test_handles_size_not_in_level_map(self):
        """Characters whose rounded size is not in size_to_level are skipped."""
        chars = [
            _make_char("H", 14.0, 10.0, 0.0),
            _make_char("i", 14.0, 10.0, 5.0),
        ]
        page = _make_page(chars, page_number=1)
        pdf = Mock()
        pdf.pages = [page]

        size_to_level = {16.0: 1}
        cfg = FontHeadingConfig()
        result = _extract_heading_text(pdf, size_to_level, cfg)

        assert len(result) == 0


class TestDeduplicateHeaders:
    """Test page header/footer deduplication."""

    def test_removes_repeated_text(self):
        """Text appearing on >30% of pages is filtered."""
        headings = [
            DetectedHeading(level=1, title="Chapter 1", page_num=1),
            DetectedHeading(level=1, title="My Document", page_num=1),
            DetectedHeading(level=1, title="My Document", page_num=2),
            DetectedHeading(level=1, title="My Document", page_num=3),
            DetectedHeading(level=1, title="My Document", page_num=4),
        ]

        result = _deduplicate_headers(headings, total_pages=10, threshold=0.3)

        titles = [h.title for h in result]
        assert "Chapter 1" in titles
        assert "My Document" not in titles

    def test_keeps_infrequent_text(self):
        """Text appearing on <=30% of pages is kept."""
        headings = [
            DetectedHeading(level=1, title="Section A", page_num=1),
            DetectedHeading(level=1, title="Section B", page_num=3),
            DetectedHeading(level=1, title="Section C", page_num=5),
        ]

        result = _deduplicate_headers(headings, total_pages=10, threshold=0.3)
        assert len(result) == 3


class TestDetectHeadingsByFont:
    """Integration tests for the full detection pipeline."""

    def test_full_pipeline(self):
        """End-to-end test with mock PDF (realistic ratio: many body chars, few heading chars)."""
        body_chars = [_make_char("x", 10.0, 100.0 + i * 2, i) for i in range(200)]
        heading_chars = [
            _make_char("I", 14.0, 10.0, 0.0),
            _make_char("n", 14.0, 10.0, 5.0),
            _make_char("t", 14.0, 10.0, 10.0),
            _make_char("r", 14.0, 10.0, 15.0),
            _make_char("o", 14.0, 10.0, 20.0),
        ]

        page = _make_page(heading_chars + body_chars, page_number=1)
        pdf = Mock()
        pdf.pages = [page]

        result = detect_headings_by_font(pdf, FontHeadingConfig(sample_interval=1))

        assert len(result) >= 1
        assert result[0]["title"] == "Intro"
        assert result[0]["level"] == 1
        assert result[0]["page_num"] == 1

    def test_returns_empty_for_no_headings(self):
        """PDF with uniform font returns empty list."""
        chars = [_make_char("x", 10.0, i) for i in range(50)]
        page = _make_page(chars, page_number=1)
        pdf = Mock()
        pdf.pages = [page]

        result = detect_headings_by_font(pdf, FontHeadingConfig(sample_interval=1))
        assert result == []

    def test_returns_empty_on_exception(self):
        """Graceful degradation on error."""
        pdf = Mock()
        type(pdf).pages = PropertyMock(side_effect=RuntimeError("corrupt"))

        result = detect_headings_by_font(pdf)
        assert result == []


class TestPDFPlumberParserIntegration:
    """Test heading_detection parameter integration in PDFPlumberParser."""

    def test_heading_detection_parameter_accepted(self):
        """Parser accepts heading_detection parameter."""
        from myrm_agent_harness.toolkits.file_parsers.pdf import PDFPlumberParser

        parser = PDFPlumberParser(heading_detection="auto")
        assert parser._heading_detection == "auto"

        parser = PDFPlumberParser(heading_detection="bookmarks")
        assert parser._heading_detection == "bookmarks"

        parser = PDFPlumberParser(heading_detection="font")
        assert parser._heading_detection == "font"

    @pytest.mark.parametrize("mode", ["auto", "font"])
    def test_font_heading_fallback_in_parse_sync(self, mode, tmp_path):
        """When no bookmarks exist, parse_sync falls back to font heading detection."""
        from unittest.mock import patch

        from myrm_agent_harness.toolkits.file_parsers.pdf import PDFPlumberParser

        parser = PDFPlumberParser(
            heading_detection=mode, extract_tables=False, extract_bookmarks=True
        )
        test_pdf = tmp_path / "test.pdf"
        test_pdf.write_text("dummy")

        body_chars = [_make_char("x", 10.0, 100.0 + i, i) for i in range(100)]
        heading_chars = [
            _make_char("T", 14.0, 10.0, 0.0),
            _make_char("e", 14.0, 10.0, 5.0),
            _make_char("s", 14.0, 10.0, 10.0),
            _make_char("t", 14.0, 10.0, 15.0),
        ]

        mock_page = Mock()
        mock_page.chars = heading_chars + body_chars
        mock_page.page_number = 1
        mock_page.extract_text = Mock(return_value="body text content")
        mock_page.extract_tables = Mock(return_value=[])
        mock_page.page_obj = Mock()
        mock_page.page_obj.pageid = 100

        mock_pdf = Mock()
        mock_pdf.pages = [mock_page]
        mock_pdf.doc = Mock()
        mock_pdf.doc.get_outlines = Mock(return_value=[])

        with patch("pdfplumber.open") as mock_open:
            mock_open.return_value.__enter__ = Mock(return_value=mock_pdf)
            mock_open.return_value.__exit__ = Mock(return_value=False)

            result = parser.parse_sync(str(test_pdf))

        assert "# Test" in result.text

    def test_bookmarks_mode_skips_font_detection(self, tmp_path):
        """When heading_detection='bookmarks', font detection is never called."""
        from unittest.mock import patch

        from myrm_agent_harness.toolkits.file_parsers.pdf import PDFPlumberParser

        parser = PDFPlumberParser(
            heading_detection="bookmarks", extract_tables=False, extract_bookmarks=True
        )
        test_pdf = tmp_path / "test.pdf"
        test_pdf.write_text("dummy")

        mock_page = Mock()
        mock_page.chars = [_make_char("x", 10.0, i) for i in range(50)]
        mock_page.page_number = 1
        mock_page.extract_text = Mock(return_value="content")
        mock_page.extract_tables = Mock(return_value=[])
        mock_page.page_obj = Mock()
        mock_page.page_obj.pageid = 100

        mock_pdf = Mock()
        mock_pdf.pages = [mock_page]
        mock_pdf.doc = Mock()
        mock_pdf.doc.get_outlines = Mock(return_value=[])

        with (
            patch("pdfplumber.open") as mock_open,
            patch(
                "myrm_agent_harness.toolkits.file_parsers.pdf_heading.detect_headings_by_font"
            ) as mock_font_detect,
        ):
            mock_open.return_value.__enter__ = Mock(return_value=mock_pdf)
            mock_open.return_value.__exit__ = Mock(return_value=False)

            parser.parse_sync(str(test_pdf))

        mock_font_detect.assert_not_called()

    def test_multi_page_font_heading_cross_pages(self, tmp_path):
        """Font heading detection works across multiple pages."""
        from unittest.mock import patch

        from myrm_agent_harness.toolkits.file_parsers.pdf import PDFPlumberParser

        parser = PDFPlumberParser(
            heading_detection="auto", extract_tables=False, extract_bookmarks=True
        )
        test_pdf = tmp_path / "test.pdf"
        test_pdf.write_text("dummy")

        def make_page_with_heading(heading_text: str, page_num: int) -> Mock:
            body = [_make_char("x", 10.0, 50.0 + i, i) for i in range(80)]
            h_chars = [
                _make_char(c, 14.0, 10.0, j * 5.0)
                for j, c in enumerate(heading_text)
            ]
            page = Mock()
            page.chars = h_chars + body
            page.page_number = page_num
            page.extract_text = Mock(return_value=f"Body text page {page_num}")
            page.extract_tables = Mock(return_value=[])
            page.page_obj = Mock()
            page.page_obj.pageid = 100 + page_num
            return page

        pages = [
            make_page_with_heading("Introduction", 1),
            make_page_with_heading("Methods", 2),
            make_page_with_heading("Results", 3),
        ]

        mock_pdf = Mock()
        mock_pdf.pages = pages
        mock_pdf.doc = Mock()
        mock_pdf.doc.get_outlines = Mock(return_value=[])

        with patch("pdfplumber.open") as mock_open:
            mock_open.return_value.__enter__ = Mock(return_value=mock_pdf)
            mock_open.return_value.__exit__ = Mock(return_value=False)
            result = parser.parse_sync(str(test_pdf))

        assert "# Introduction" in result.text
        assert "# Methods" in result.text
        assert "# Results" in result.text

    def test_bookmarks_present_suppresses_font_detection(self, tmp_path):
        """When bookmarks are successfully extracted, font detection is not triggered."""
        from unittest.mock import patch

        from myrm_agent_harness.toolkits.file_parsers.pdf import PDFPlumberParser

        parser = PDFPlumberParser(
            heading_detection="auto", extract_tables=False, extract_bookmarks=True
        )
        test_pdf = tmp_path / "test.pdf"
        test_pdf.write_text("dummy")

        mock_page = Mock()
        mock_page.chars = [_make_char("x", 10.0, i) for i in range(50)]
        mock_page.page_number = 1
        mock_page.extract_text = Mock(return_value="content")
        mock_page.extract_tables = Mock(return_value=[])
        mock_page.page_obj = Mock()
        mock_page.page_obj.pageid = 100

        mock_pdf = Mock()
        mock_pdf.pages = [mock_page]
        mock_pdf.doc = Mock()
        mock_pdf.doc.get_outlines = Mock(
            return_value=[(1, "Chapter 1", [Mock(objid=100)], None, None)]
        )

        with (
            patch("pdfplumber.open") as mock_open,
            patch(
                "myrm_agent_harness.toolkits.file_parsers.pdf_heading.detect_headings_by_font"
            ) as mock_font_detect,
        ):
            mock_open.return_value.__enter__ = Mock(return_value=mock_pdf)
            mock_open.return_value.__exit__ = Mock(return_value=False)
            result = parser.parse_sync(str(test_pdf))

        mock_font_detect.assert_not_called()
        assert "# Chapter 1" in result.text

    def test_parallel_mode_with_font_heading(self, tmp_path):
        """Font heading detection works together with parallel page parsing."""
        from unittest.mock import patch

        from myrm_agent_harness.toolkits.file_parsers.pdf import PDFPlumberParser

        parser = PDFPlumberParser(
            heading_detection="auto",
            extract_tables=False,
            extract_bookmarks=True,
            parallel=True,
            max_workers=2,
        )
        test_pdf = tmp_path / "test.pdf"
        test_pdf.write_text("dummy")

        pages = []
        for i in range(12):
            body = [_make_char("x", 10.0, 50.0 + j, j) for j in range(60)]
            h_chars = [_make_char(c, 14.0, 10.0, j * 5.0) for j, c in enumerate(f"Sec{i}")]
            page = Mock()
            page.chars = h_chars + body
            page.page_number = i + 1
            page.extract_text = Mock(return_value=f"page {i + 1}")
            page.extract_tables = Mock(return_value=[])
            page.page_obj = Mock()
            page.page_obj.pageid = 100 + i
            pages.append(page)

        mock_pdf = Mock()
        mock_pdf.pages = pages
        mock_pdf.doc = Mock()
        mock_pdf.doc.get_outlines = Mock(return_value=[])

        with patch("pdfplumber.open") as mock_open:
            mock_open.return_value.__enter__ = Mock(return_value=mock_pdf)
            mock_open.return_value.__exit__ = Mock(return_value=False)
            result = parser.parse_sync(str(test_pdf))

        assert result.metadata["page_count"] == 12
        assert "# Sec0" in result.text
        assert "# Sec11" in result.text

    def test_dedup_filters_headers_in_multi_page(self):
        """Headers appearing on many pages (like page footers) are filtered out."""
        body_chars = [_make_char("x", 10.0, 50.0 + i, i) for i in range(100)]

        pages = []
        for i in range(10):
            h_chars = [
                _make_char(c, 14.0, 10.0, j * 5.0) for j, c in enumerate("Footer Text")
            ]
            unique_h = [
                _make_char(c, 14.0, 30.0, j * 5.0) for j, c in enumerate(f"Chapter {i}")
            ]
            page = _make_page(h_chars + unique_h + body_chars, page_number=i + 1)
            pages.append(page)

        pdf = Mock()
        pdf.pages = pages

        result = detect_headings_by_font(pdf, FontHeadingConfig(sample_interval=1))

        titles = [h["title"] for h in result]
        assert "Footer Text" not in titles
        assert any(t.startswith("Chapter") for t in titles)

    def test_custom_config_integration(self):
        """Custom FontHeadingConfig parameters are respected."""
        body_chars = [_make_char("x", 10.0, 100.0 + i, i) for i in range(200)]
        heading_chars = [_make_char(c, 11.0, 10.0, j * 5.0) for j, c in enumerate("SmallH")]

        page = _make_page(heading_chars + body_chars, page_number=1)
        pdf = Mock()
        pdf.pages = [page]

        strict_config = FontHeadingConfig(min_delta=3.0, sample_interval=1)
        result = detect_headings_by_font(pdf, strict_config)
        assert len(result) == 0

        loose_config = FontHeadingConfig(min_delta=0.5, sample_interval=1)
        result = detect_headings_by_font(pdf, loose_config)
        assert len(result) >= 1

    def test_get_parser_returns_auto_heading_mode(self):
        """Default parser from get_parser uses heading_detection='auto'."""
        from myrm_agent_harness.toolkits.file_parsers import get_parser

        parser = get_parser("document.pdf")
        assert parser._heading_detection == "auto"
