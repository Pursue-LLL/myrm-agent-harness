"""Unit tests for PDF bookmark extraction functionality."""

from unittest.mock import Mock, patch

import pytest

from myrm_agent_harness.toolkits.file_parsers.pdf import PDFPlumberParser


class TestPDFBookmarkExtraction:
    """Test PDF bookmark/outline extraction with nested hierarchy and page resolution."""

    @pytest.fixture
    def parser(self):
        """Create PDF parser instance with bookmark extraction enabled."""
        return PDFPlumberParser(extract_bookmarks=True, extract_tables=False)

    @pytest.fixture
    def mock_pdf(self):
        """Create mock PDF object with pages."""
        pdf = Mock()
        pdf.pages = [Mock() for _ in range(10)]
        for idx, page in enumerate(pdf.pages):
            page.page_obj = Mock()
            page.page_obj.pageid = 100 + idx  # Simulated page object IDs
        return pdf

    # ============== Build Page Number Map Tests ==============

    def test_build_page_number_map_basic(self, parser, mock_pdf):
        """Test building page number map from PDF pages."""
        page_map = parser._build_page_number_map(mock_pdf)

        assert len(page_map) == 10
        assert page_map[100] == 1  # First page
        assert page_map[109] == 10  # Last page

    def test_build_page_number_map_legacy_objid(self, parser):
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

        page_map = parser._build_page_number_map(mock_pdf)

        assert page_map[50] == 1
        assert page_map[51] == 2

    def test_build_page_number_map_missing_page_obj(self, parser):
        """Test page map handles missing page_obj gracefully."""
        mock_pdf = Mock()
        mock_pdf.pages = [Mock(), Mock()]

        # First page missing page_obj
        del mock_pdf.pages[0].page_obj

        # Second page normal
        mock_pdf.pages[1].page_obj = Mock()
        mock_pdf.pages[1].page_obj.pageid = 100

        page_map = parser._build_page_number_map(mock_pdf)

        assert len(page_map) == 1  # Only second page
        assert page_map[100] == 2

    # ============== Resolve Bookmark Page Tests ==============

    def test_resolve_bookmark_page_by_objid(self, parser):
        """Test resolving bookmark page by object ID."""
        page_ref = Mock()
        page_ref.objid = 100
        page_map = {100: 1, 101: 2, 102: 3}

        page_num = parser._resolve_bookmark_page(page_ref, page_map, 10)
        assert page_num == 1

    def test_resolve_bookmark_page_by_int_zero_based(self, parser):
        """Test resolving bookmark page by 0-based integer index."""
        page_ref = 2  # 0-based index
        page_map = {}

        page_num = parser._resolve_bookmark_page(page_ref, page_map, 10)
        assert page_num == 3  # Converted to 1-based

    def test_resolve_bookmark_page_int_out_of_range(self, parser):
        """Test integer page reference out of range."""
        page_ref = 100  # Way beyond total pages
        page_map = {}

        page_num = parser._resolve_bookmark_page(page_ref, page_map, 10)
        assert page_num is None

    def test_resolve_bookmark_page_by_lazy_resolve(self, parser):
        """Test resolving bookmark page via lazy resolve() method."""
        page_ref = Mock()
        del page_ref.objid  # No direct objid

        resolved = Mock()
        resolved.pageid = 100
        page_ref.resolve = Mock(return_value=resolved)

        page_map = {100: 1}

        page_num = parser._resolve_bookmark_page(page_ref, page_map, 10)
        assert page_num == 1
        page_ref.resolve.assert_called_once()

    def test_resolve_bookmark_page_lazy_resolve_fallback_objid(self, parser):
        """Test lazy resolve fallback to objid attribute."""
        page_ref = Mock()
        del page_ref.objid  # No direct objid

        resolved = Mock()
        resolved.objid = 100  # Uses objid instead of pageid
        del resolved.pageid
        page_ref.resolve = Mock(return_value=resolved)

        page_map = {100: 1}

        page_num = parser._resolve_bookmark_page(page_ref, page_map, 10)
        assert page_num == 1

    def test_resolve_bookmark_page_resolve_fails(self, parser):
        """Test resolve() method fails gracefully."""
        page_ref = Mock()
        del page_ref.objid
        page_ref.resolve = Mock(side_effect=Exception("Resolve error"))

        page_map = {100: 1}

        page_num = parser._resolve_bookmark_page(page_ref, page_map, 10)
        assert page_num is None  # Should not raise exception

    def test_resolve_bookmark_page_unknown_format(self, parser):
        """Test unknown page reference format returns None."""
        page_ref = "unknown-format"  # Neither int nor object
        page_map = {100: 1}

        page_num = parser._resolve_bookmark_page(page_ref, page_map, 10)
        assert page_num is None

    # ============== Extract Bookmarks Tests ==============

    def test_extract_bookmarks_basic(self, parser):
        """Test basic bookmark extraction."""
        mock_pdf = Mock()
        mock_pdf.doc = Mock()
        mock_pdf.doc.get_outlines = Mock(
            return_value=[
                (1, "Chapter 1", [Mock(objid=100)], None, None),
                (2, "Section 1.1", [Mock(objid=101)], None, None),
                (1, "Chapter 2", [Mock(objid=102)], None, None),
            ]
        )
        mock_pdf.pages = [Mock() for _ in range(3)]
        for idx, page in enumerate(mock_pdf.pages):
            page.page_obj = Mock()
            page.page_obj.pageid = 100 + idx

        bookmarks = parser._extract_bookmarks(mock_pdf)

        assert len(bookmarks) == 3
        assert bookmarks[0]["level"] == 1
        assert bookmarks[0]["title"] == "Chapter 1"
        assert bookmarks[0]["page_num"] == 1

        assert bookmarks[1]["level"] == 2
        assert bookmarks[1]["title"] == "Section 1.1"
        assert bookmarks[1]["page_num"] == 2

        assert bookmarks[2]["level"] == 1
        assert bookmarks[2]["title"] == "Chapter 2"
        assert bookmarks[2]["page_num"] == 3

    def test_extract_bookmarks_level_clamping(self, parser):
        """Test bookmark level is clamped between 1-6."""
        mock_pdf = Mock()
        mock_pdf.doc = Mock()
        mock_pdf.doc.get_outlines = Mock(
            return_value=[
                (0, "Level 0 (clamped to 1)", [Mock(objid=100)], None, None),
                (10, "Level 10 (clamped to 6)", [Mock(objid=101)], None, None),
            ]
        )
        mock_pdf.pages = [Mock() for _ in range(2)]
        for idx, page in enumerate(mock_pdf.pages):
            page.page_obj = Mock()
            page.page_obj.pageid = 100 + idx

        bookmarks = parser._extract_bookmarks(mock_pdf)

        assert bookmarks[0]["level"] == 1  # Clamped from 0
        assert bookmarks[1]["level"] == 6  # Clamped from 10

    def test_extract_bookmarks_empty_title_skipped(self, parser):
        """Test bookmarks with empty titles are skipped."""
        mock_pdf = Mock()
        mock_pdf.doc = Mock()
        mock_pdf.doc.get_outlines = Mock(
            return_value=[
                (1, "", [Mock(objid=100)], None, None),  # Empty title
                (1, "   ", [Mock(objid=101)], None, None),  # Whitespace only
                (1, "Valid Title", [Mock(objid=102)], None, None),
            ]
        )
        mock_pdf.pages = [Mock() for _ in range(3)]
        for idx, page in enumerate(mock_pdf.pages):
            page.page_obj = Mock()
            page.page_obj.pageid = 100 + idx

        bookmarks = parser._extract_bookmarks(mock_pdf)

        assert len(bookmarks) == 1
        assert bookmarks[0]["title"] == "Valid Title"

    def test_extract_bookmarks_unresolved_page(self, parser):
        """Test bookmarks with unresolved pages still included."""
        mock_pdf = Mock()
        mock_pdf.doc = Mock()
        mock_pdf.doc.get_outlines = Mock(
            return_value=[
                (1, "Resolvable", [Mock(objid=100)], None, None),
                (1, "Unresolvable", [Mock(objid=999)], None, None),  # ID not in page map
            ]
        )
        mock_pdf.pages = [Mock()]
        mock_pdf.pages[0].page_obj = Mock()
        mock_pdf.pages[0].page_obj.pageid = 100

        bookmarks = parser._extract_bookmarks(mock_pdf)

        assert len(bookmarks) == 2
        assert bookmarks[0]["page_num"] == 1
        assert bookmarks[1]["page_num"] is None  # Unresolved

    def test_extract_bookmarks_empty_dest(self, parser):
        """Test bookmarks with empty destination list."""
        mock_pdf = Mock()
        mock_pdf.doc = Mock()
        mock_pdf.doc.get_outlines = Mock(
            return_value=[
                (1, "No Dest", [], None, None),  # Empty dest
                (1, "None Dest", None, None, None),  # None dest
            ]
        )
        mock_pdf.pages = []

        bookmarks = parser._extract_bookmarks(mock_pdf)

        assert len(bookmarks) == 2
        assert bookmarks[0]["page_num"] is None
        assert bookmarks[1]["page_num"] is None

    def test_extract_bookmarks_no_outline_support(self, parser):
        """Test PDF without outline support returns empty list."""
        mock_pdf = Mock()
        mock_pdf.doc = None  # No doc attribute

        bookmarks = parser._extract_bookmarks(mock_pdf)

        assert bookmarks == []

    def test_extract_bookmarks_no_outlines(self, parser):
        """Test PDF with no bookmarks returns empty list."""
        mock_pdf = Mock()
        mock_pdf.doc = Mock()
        mock_pdf.doc.get_outlines = Mock(return_value=[])

        bookmarks = parser._extract_bookmarks(mock_pdf)

        assert bookmarks == []

    def test_extract_bookmarks_exception_handling(self, parser):
        """Test bookmark extraction handles exceptions gracefully."""
        mock_pdf = Mock()
        mock_pdf.doc = Mock()
        mock_pdf.doc.get_outlines = Mock(side_effect=Exception("Outline error"))

        bookmarks = parser._extract_bookmarks(mock_pdf)

        assert bookmarks == []  # Should not raise exception

    # ============== Integration with parse_sync Tests ==============

    @pytest.mark.skip(reason="Needs pdfplumber to be installed")
    @patch("pdfplumber.open")
    def test_parse_sync_with_bookmarks(self, mock_open, parser, tmp_path):
        """Test parse_sync integrates bookmark extraction and injection."""
        test_pdf = tmp_path / "test.pdf"
        test_pdf.write_text("dummy pdf content")

        # Setup mock PDF
        mock_pdf = Mock()
        mock_pdf.pages = [Mock(), Mock()]
        for idx, page in enumerate(mock_pdf.pages):
            page.extract_text = Mock(return_value=f"Page {idx + 1} content")
            page.extract_tables = Mock(return_value=[])
            page.page_obj = Mock()
            page.page_obj.pageid = 100 + idx

        mock_pdf.doc = Mock()
        mock_pdf.doc.get_outlines = Mock(
            return_value=[
                (1, "Chapter 1", [Mock(objid=100)], None, None),
                (2, "Section 1.1", [Mock(objid=101)], None, None),
            ]
        )

        mock_open.return_value.__enter__ = Mock(return_value=mock_pdf)
        mock_open.return_value.__exit__ = Mock(return_value=False)

        result = parser.parse_sync(str(test_pdf))

        # Verify bookmarks were extracted
        assert result.metadata["bookmarks_total"] == 2
        assert result.metadata["bookmarks_resolved"] == 2
        assert result.metadata["bookmarks_unresolved"] == 0

        # Verify bookmarks were injected as Markdown headings
        assert "# Chapter 1" in result.text
        assert "## Section 1.1" in result.text

        # Verify page content follows bookmarks
        assert "[Page 1]" in result.text
        assert "[Page 2]" in result.text

    @pytest.mark.skip(reason="Needs pdfplumber to be installed")
    @patch("pdfplumber.open")
    def test_parse_sync_without_bookmarks(self, mock_open, tmp_path):
        """Test parse_sync with bookmark extraction disabled."""
        parser = PDFPlumberParser(extract_bookmarks=False)
        test_pdf = tmp_path / "test.pdf"
        test_pdf.write_text("dummy pdf content")

        mock_pdf = Mock()
        mock_pdf.pages = [Mock()]
        mock_pdf.pages[0].extract_text = Mock(return_value="Content")
        mock_pdf.pages[0].extract_tables = Mock(return_value=[])

        mock_open.return_value.__enter__ = Mock(return_value=mock_pdf)
        mock_open.return_value.__exit__ = Mock(return_value=False)

        result = parser.parse_sync(str(test_pdf))

        # Verify no bookmark metadata
        assert "bookmarks_total" not in result.metadata

        # Verify no Markdown headings injected
        assert "#" not in result.text
