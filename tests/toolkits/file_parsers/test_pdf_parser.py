"""Unit tests for PDFPlumberParser core parsing logic."""

from unittest.mock import Mock, patch

import pytest

from myrm_agent_harness.toolkits.file_parsers.pdf import PDFPlumberParser, PDFTable


def _make_mock_page(
    text: str = "Page content",
    tables: list[list[list[str]]] | None = None,
    page_obj_id: int = 100,
) -> Mock:
    """Create a mock pdfplumber page."""
    page = Mock()
    page.extract_text = Mock(return_value=text)
    page.extract_tables = Mock(return_value=tables or [])
    page.page_obj = Mock()
    page.page_obj.pageid = page_obj_id
    return page


def _make_mock_pdf(pages: list[Mock], outlines: list | None = None) -> Mock:
    """Create a mock pdfplumber PDF."""
    pdf = Mock()
    pdf.pages = pages
    pdf.doc = Mock()
    pdf.doc.get_outlines = Mock(return_value=outlines or [])
    return pdf


class TestParseAsync:
    """Test async parse and parse_with_tables methods."""

    @pytest.mark.asyncio
    async def test_parse_returns_text(self, tmp_path):
        """parse() returns extracted text."""
        parser = PDFPlumberParser(extract_tables=False, extract_bookmarks=False)
        test_pdf = tmp_path / "test.pdf"
        test_pdf.write_text("dummy")

        mock_page = _make_mock_page("Hello world")
        mock_pdf = _make_mock_pdf([mock_page])

        with patch("pdfplumber.open") as mock_open:
            mock_open.return_value.__enter__ = Mock(return_value=mock_pdf)
            mock_open.return_value.__exit__ = Mock(return_value=False)
            result = await parser.parse(str(test_pdf))

        assert "Hello world" in result

    @pytest.mark.asyncio
    async def test_parse_file_not_found(self, tmp_path):
        """parse() raises FileNotFoundError for missing file."""
        parser = PDFPlumberParser()
        with pytest.raises(FileNotFoundError):
            await parser.parse(str(tmp_path / "nonexistent.pdf"))

    @pytest.mark.asyncio
    async def test_parse_with_tables_returns_result(self, tmp_path):
        """parse_with_tables() returns PDFParseResult."""
        parser = PDFPlumberParser(extract_tables=False, extract_bookmarks=False)
        test_pdf = tmp_path / "test.pdf"
        test_pdf.write_text("dummy")

        mock_page = _make_mock_page("Content")
        mock_pdf = _make_mock_pdf([mock_page])

        with patch("pdfplumber.open") as mock_open:
            mock_open.return_value.__enter__ = Mock(return_value=mock_pdf)
            mock_open.return_value.__exit__ = Mock(return_value=False)
            result = await parser.parse_with_tables(str(test_pdf))

        assert result.text
        assert result.metadata["page_count"] == 1

    @pytest.mark.asyncio
    async def test_parse_with_tables_file_not_found(self, tmp_path):
        """parse_with_tables() raises FileNotFoundError for missing file."""
        parser = PDFPlumberParser()
        with pytest.raises(FileNotFoundError):
            await parser.parse_with_tables(str(tmp_path / "nonexistent.pdf"))


class TestParseSyncImportError:
    """Test pdfplumber import error handling."""

    def test_import_error(self, tmp_path):
        """parse_sync raises ImportError when pdfplumber unavailable."""
        parser = PDFPlumberParser()
        test_pdf = tmp_path / "test.pdf"
        test_pdf.write_text("dummy")

        with patch.dict("sys.modules", {"pdfplumber": None}):
            with patch("builtins.__import__", side_effect=ImportError("no pdfplumber")):
                with pytest.raises(ImportError, match="pdfplumber"):
                    parser.parse_sync(str(test_pdf))


class TestTableExtraction:
    """Test table extraction and formatting."""

    def test_extract_page_tables(self):
        """Tables are extracted and cleaned."""
        parser = PDFPlumberParser(extract_tables=True, extract_bookmarks=False)
        page = Mock()
        page.extract_tables = Mock(
            return_value=[[["Header1", "Header2"], ["val1", "val2"], ["val3", None]]]
        )

        tables = parser._extract_page_tables(page)

        assert len(tables) == 1
        assert tables[0].data[0] == ["Header1", "Header2"]
        assert tables[0].data[2] == ["val3", ""]

    def test_extract_tables_empty(self):
        """Empty tables return empty list."""
        parser = PDFPlumberParser(extract_tables=True)
        page = Mock()
        page.extract_tables = Mock(return_value=[])

        tables = parser._extract_page_tables(page)
        assert tables == []

    def test_extract_tables_exception(self):
        """Table extraction exception is handled gracefully."""
        parser = PDFPlumberParser(extract_tables=True)
        page = Mock()
        page.extract_tables = Mock(side_effect=RuntimeError("corrupt"))

        tables = parser._extract_page_tables(page)
        assert tables == []

    def test_clean_table_data_removes_empty_rows(self):
        """Rows with all empty cells are removed."""
        result = PDFPlumberParser._clean_table_data(
            [["a", "b"], [None, None], ["c", ""]]
        )
        assert len(result) == 2
        assert result[0] == ["a", "b"]
        assert result[1] == ["c", ""]


class TestTableFormatting:
    """Test Markdown table formatting."""

    def test_format_table_markdown_basic(self):
        """Formats table with headers and data rows."""
        table = PDFTable(
            page_number=1,
            table_index=0,
            data=[["Name", "Age"], ["Alice", "30"], ["Bob", "25"]],
            bbox=None,
        )
        result = PDFPlumberParser._format_table_markdown(table)

        assert "| Name | Age |" in result
        assert "| --- | --- |" in result
        assert "| Alice | 30 |" in result

    def test_format_table_markdown_empty(self):
        """Empty table produces fallback text."""
        table = PDFTable(page_number=1, table_index=0, data=[], bbox=None)
        result = PDFPlumberParser._format_table_markdown(table)
        assert "empty" in result.lower()

    def test_format_table_markdown_single_row(self):
        """Table with only headers (no data) produces fallback."""
        table = PDFTable(
            page_number=1, table_index=0, data=[["Col1"]], bbox=None
        )
        result = PDFPlumberParser._format_table_markdown(table)
        assert "empty" in result.lower()

    def test_format_table_escapes_pipe(self):
        """Pipe characters in cells are escaped."""
        table = PDFTable(
            page_number=1,
            table_index=0,
            data=[["A|B", "C"], ["D", "E|F"]],
            bbox=None,
        )
        result = PDFPlumberParser._format_table_markdown(table)
        assert "A\\|B" in result
        assert "E\\|F" in result

    def test_format_table_pads_short_rows(self):
        """Rows shorter than header are padded."""
        table = PDFTable(
            page_number=1,
            table_index=0,
            data=[["H1", "H2", "H3"], ["a"]],
            bbox=None,
        )
        result = PDFPlumberParser._format_table_markdown(table)
        assert result.count("|") > 0


class TestTableSummaryL0:
    """Test L0 summary generation."""

    def test_empty_table(self):
        """Empty table returns 'Empty table'."""
        table = PDFTable(page_number=1, table_index=0, data=[], bbox=None)
        result = PDFPlumberParser._generate_table_summary_l0(table)
        assert result == "Empty table"

    def test_basic_summary(self):
        """Summary includes row count and headers."""
        table = PDFTable(
            page_number=2,
            table_index=0,
            data=[["Name", "Score", "Grade"], ["Alice", "95", "A"]],
            bbox=None,
        )
        result = PDFPlumberParser._generate_table_summary_l0(table)

        assert "Page 2" in result
        assert "Rows: 1" in result
        assert "Name" in result
        assert "Data sample" in result

    def test_summary_truncates_many_columns(self):
        """Summary truncates column display at 5."""
        table = PDFTable(
            page_number=1,
            table_index=0,
            data=[["A", "B", "C", "D", "E", "F", "G"], ["1", "2", "3", "4", "5", "6", "7"]],
            bbox=None,
        )
        result = PDFPlumberParser._generate_table_summary_l0(table)
        assert "..." in result


class TestParallelParsing:
    """Test parallel page parsing."""

    def test_parallel_mode_activated(self, tmp_path):
        """Parallel mode triggers for >10 pages."""
        parser = PDFPlumberParser(
            parallel=True, extract_tables=False, extract_bookmarks=False
        )
        test_pdf = tmp_path / "test.pdf"
        test_pdf.write_text("dummy")

        pages = [_make_mock_page(f"Page {i}", page_obj_id=100 + i) for i in range(12)]
        mock_pdf = _make_mock_pdf(pages)

        with patch("pdfplumber.open") as mock_open:
            mock_open.return_value.__enter__ = Mock(return_value=mock_pdf)
            mock_open.return_value.__exit__ = Mock(return_value=False)
            result = parser.parse_sync(str(test_pdf))

        assert result.metadata["page_count"] == 12
        assert "Page 0" in result.text
        assert "Page 11" in result.text


class TestErrorHandling:
    """Test page-level error handling."""

    def test_page_error_recorded(self, tmp_path):
        """Parsing errors on individual pages are captured."""
        parser = PDFPlumberParser(extract_tables=False, extract_bookmarks=False)
        test_pdf = tmp_path / "test.pdf"
        test_pdf.write_text("dummy")

        page1 = _make_mock_page("Good page")
        page2 = Mock()
        page2.extract_text = Mock(side_effect=RuntimeError("corrupt page"))
        page2.extract_tables = Mock(return_value=[])
        page2.page_obj = Mock()
        page2.page_obj.pageid = 101

        mock_pdf = _make_mock_pdf([page1, page2])

        with patch("pdfplumber.open") as mock_open:
            mock_open.return_value.__enter__ = Mock(return_value=mock_pdf)
            mock_open.return_value.__exit__ = Mock(return_value=False)
            result = parser.parse_sync(str(test_pdf))

        assert result.metadata["failed_pages"] == 1
        assert "Parsing Error" in result.text


class TestMergeTextAndTables:
    """Test text and table merging logic."""

    def test_inline_table_format(self):
        """Tables in inline mode appear as Markdown."""
        parser = PDFPlumberParser(table_format="inline")
        tables = [
            PDFTable(
                page_number=1,
                table_index=0,
                data=[["H1", "H2"], ["a", "b"]],
                bbox=None,
                id="table_1_0",
                markdown="| H1 | H2 |\n| --- | --- |\n| a | b |",
                summary_l0="Summary",
            )
        ]
        result = parser._merge_text_and_tables(["[Page 1]\nText"], tables)
        assert "| H1 | H2 |" in result

    def test_placeholder_table_format(self):
        """Tables in placeholder mode use TABLE_CAPSULE."""
        parser = PDFPlumberParser(table_format="placeholder")
        tables = [
            PDFTable(
                page_number=1,
                table_index=0,
                data=[["H1"], ["a"]],
                bbox=None,
                id="table_1_0",
                markdown="md",
                summary_l0="Table summary here",
            )
        ]
        result = parser._merge_text_and_tables(["[Page 1]\nText"], tables)
        assert "TABLE_CAPSULE: table_1_0" in result
        assert "Table summary here" in result


class TestSupportedExtensions:
    """Test parser extension support."""

    def test_supports_pdf(self):
        """Parser declares .pdf support."""
        parser = PDFPlumberParser()
        assert ".pdf" in parser.supported_extensions
