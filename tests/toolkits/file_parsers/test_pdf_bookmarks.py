"""Unit tests for PDF bookmark extraction and the generic-title quality gate."""

from unittest.mock import Mock

from myrm_agent_harness.toolkits.file_parsers.base import PDFHeading
from myrm_agent_harness.toolkits.file_parsers.pdf.pdf_bookmarks import (
    _build_page_number_map,
    _resolve_bookmark_page,
    bookmarks_are_degenerate,
    extract_bookmarks,
)


class TestPDFBookmarkExtraction:
    """Test PDF bookmark/outline extraction with nested hierarchy and page resolution."""

    @staticmethod
    def mock_pdf(page_count: int) -> Mock:
        pdf = Mock()
        pdf.pages = [Mock() for _ in range(page_count)]
        for idx, page in enumerate(pdf.pages):
            page.page_obj = Mock()
            page.page_obj.pageid = 100 + idx
        return pdf

    # ============== Build Page Number Map Tests ==============

    def test_build_page_number_map_basic(self):
        """Test building page number map from PDF pages."""
        page_map = _build_page_number_map(self.mock_pdf(10))

        assert len(page_map) == 10
        assert page_map[100] == 1  # First page
        assert page_map[109] == 10  # Last page

    def test_build_page_number_map_legacy_objid(self):
        """Test page map with legacy objid attribute."""
        mock_pdf = Mock()
        mock_pdf.pages = [Mock(), Mock()]

        # First page uses objid (legacy)
        mock_pdf.pages[0].page_obj = Mock()
        mock_pdf.pages[0].page_obj.objid = 50
        del mock_pdf.pages[0].page_obj.pageid

        # Second page uses pageid (modern)
        mock_pdf.pages[1].page_obj = Mock()
        mock_pdf.pages[1].page_obj.pageid = 51

        page_map = _build_page_number_map(mock_pdf)

        assert page_map[50] == 1
        assert page_map[51] == 2

    def test_build_page_number_map_missing_page_obj(self):
        """Test page map handles missing page_obj gracefully."""
        mock_pdf = Mock()
        mock_pdf.pages = [Mock(), Mock()]

        # First page missing page_obj
        del mock_pdf.pages[0].page_obj

        # Second page normal
        mock_pdf.pages[1].page_obj = Mock()
        mock_pdf.pages[1].page_obj.pageid = 100

        page_map = _build_page_number_map(mock_pdf)

        assert len(page_map) == 1  # Only second page
        assert page_map[100] == 2

    # ============== Resolve Bookmark Page Tests ==============

    def test_resolve_bookmark_page_by_objid(self):
        """Test resolving bookmark page by object ID."""
        page_ref = Mock()
        page_ref.objid = 100
        page_map = {100: 1, 101: 2, 102: 3}

        assert _resolve_bookmark_page(page_ref, page_map, 10) == 1

    def test_resolve_bookmark_page_by_int_zero_based(self):
        """Test resolving bookmark page by 0-based integer index."""
        assert _resolve_bookmark_page(2, {}, 10) == 3  # Converted to 1-based

    def test_resolve_bookmark_page_int_out_of_range(self):
        """Test integer page reference out of range."""
        assert _resolve_bookmark_page(100, {}, 10) is None

    def test_resolve_bookmark_page_by_lazy_resolve(self):
        """Test resolving bookmark page via lazy resolve() method."""
        page_ref = Mock()
        del page_ref.objid  # No direct objid

        resolved = Mock()
        resolved.pageid = 100
        page_ref.resolve = Mock(return_value=resolved)

        assert _resolve_bookmark_page(page_ref, {100: 1}, 10) == 1
        page_ref.resolve.assert_called_once()

    def test_resolve_bookmark_page_lazy_resolve_fallback_objid(self):
        """Test lazy resolve fallback to objid attribute."""
        page_ref = Mock()
        del page_ref.objid

        resolved = Mock()
        resolved.objid = 100
        del resolved.pageid
        page_ref.resolve = Mock(return_value=resolved)

        assert _resolve_bookmark_page(page_ref, {100: 1}, 10) == 1

    def test_resolve_bookmark_page_resolve_fails(self):
        """Test resolve() method fails gracefully."""
        page_ref = Mock()
        del page_ref.objid
        page_ref.resolve = Mock(side_effect=Exception("Resolve error"))

        assert _resolve_bookmark_page(page_ref, {100: 1}, 10) is None

    def test_resolve_bookmark_page_unknown_format(self):
        """Test unknown page reference format returns None."""
        assert _resolve_bookmark_page("unknown-format", {100: 1}, 10) is None

    # ============== Extract Bookmarks Tests ==============

    def test_extract_bookmarks_basic(self):
        """Test basic bookmark extraction with resolved pages."""
        mock_pdf = self.mock_pdf(3)
        mock_pdf.doc = Mock()
        mock_pdf.doc.get_outlines = Mock(
            return_value=[
                (1, "Chapter 1", [Mock(objid=100)], None, None),
                (2, "Section 1.1", [Mock(objid=101)], None, None),
                (1, "Chapter 2", [Mock(objid=102)], None, None),
            ]
        )

        bookmarks = extract_bookmarks(mock_pdf)

        assert bookmarks == [
            PDFHeading(level=1, title="Chapter 1", page_num=1),
            PDFHeading(level=2, title="Section 1.1", page_num=2),
            PDFHeading(level=1, title="Chapter 2", page_num=3),
        ]

    def test_extract_bookmarks_level_clamping(self):
        """Test bookmark level is clamped between 1-6."""
        mock_pdf = self.mock_pdf(2)
        mock_pdf.doc = Mock()
        mock_pdf.doc.get_outlines = Mock(
            return_value=[
                (0, "Level 0 (clamped to 1)", [Mock(objid=100)], None, None),
                (10, "Level 10 (clamped to 6)", [Mock(objid=101)], None, None),
            ]
        )

        bookmarks = extract_bookmarks(mock_pdf)

        assert bookmarks[0].level == 1  # Clamped from 0
        assert bookmarks[1].level == 6  # Clamped from 10

    def test_extract_bookmarks_empty_title_skipped(self):
        """Test bookmarks with empty titles are skipped."""
        mock_pdf = self.mock_pdf(3)
        mock_pdf.doc = Mock()
        mock_pdf.doc.get_outlines = Mock(
            return_value=[
                (1, "", [Mock(objid=100)], None, None),
                (1, "   ", [Mock(objid=101)], None, None),
                (1, "Valid Title", [Mock(objid=102)], None, None),
            ]
        )

        bookmarks = extract_bookmarks(mock_pdf)

        assert len(bookmarks) == 1
        assert bookmarks[0].title == "Valid Title"

    def test_extract_bookmarks_unresolved_page_skipped(self):
        """Unresolvable destinations cannot be placed in text and are dropped."""
        mock_pdf = self.mock_pdf(1)
        mock_pdf.doc = Mock()
        mock_pdf.doc.get_outlines = Mock(
            return_value=[
                (1, "Resolvable", [Mock(objid=100)], None, None),
                (1, "Unresolvable", [Mock(objid=999)], None, None),
            ]
        )

        bookmarks = extract_bookmarks(mock_pdf)

        assert bookmarks == [PDFHeading(level=1, title="Resolvable", page_num=1)]

    def test_extract_bookmarks_empty_dest(self):
        """Test bookmarks with empty or missing destinations are skipped."""
        mock_pdf = Mock()
        mock_pdf.doc = Mock()
        mock_pdf.doc.get_outlines = Mock(
            return_value=[
                (1, "No Dest", [], None, None),
                (1, "None Dest", None, None, None),
            ]
        )
        mock_pdf.pages = []

        assert extract_bookmarks(mock_pdf) == []

    def test_extract_bookmarks_no_outline_support(self):
        """Test PDF without outline support returns empty list."""
        mock_pdf = Mock()
        mock_pdf.doc = None

        assert extract_bookmarks(mock_pdf) == []

    def test_extract_bookmarks_no_outlines(self):
        """Test PDF with no bookmarks returns empty list."""
        mock_pdf = Mock()
        mock_pdf.doc = Mock()
        mock_pdf.doc.get_outlines = Mock(return_value=[])

        assert extract_bookmarks(mock_pdf) == []

    def test_extract_bookmarks_exception_handling(self):
        """Test bookmark extraction handles exceptions gracefully."""
        mock_pdf = Mock()
        mock_pdf.doc = Mock()
        mock_pdf.doc.get_outlines = Mock(side_effect=Exception("Outline error"))

        assert extract_bookmarks(mock_pdf) == []


class TestBookmarkQualityGate:
    """Generic exporter titles must not suppress detection nor become headings."""

    def test_slide_export_titles_are_degenerate(self):
        headings = [PDFHeading(level=1, title=f"幻灯片 {idx}", page_num=idx) for idx in range(1, 21)]

        assert bookmarks_are_degenerate(headings) is True

    def test_real_titles_are_not_degenerate(self):
        headings = [
            PDFHeading(level=1, title="第一部分 · 行业背景", page_num=1),
            PDFHeading(level=1, title="第二部分 · 现实问题", page_num=3),
            PDFHeading(level=1, title="第三部分 · 优势总览", page_num=5),
        ]

        assert bookmarks_are_degenerate(headings) is False

    def test_few_bookmarks_are_never_degenerate(self):
        headings = [PDFHeading(level=1, title="幻灯片 1", page_num=1)]

        assert bookmarks_are_degenerate(headings) is False
