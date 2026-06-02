from unittest.mock import MagicMock, patch

import pytest

from myrm_agent_harness.toolkits.file_parsers.pdf import PDFPlumberParser
from myrm_agent_harness.toolkits.file_parsers.pdf_content_extractor import (
    PDFExtractConfig,
    extract_pdf_content,
)


def test_table_summary_l0_generation():
    """Test the heuristic L0 summary generation."""
    parser = PDFPlumberParser()
    from myrm_agent_harness.toolkits.file_parsers.base import PDFTable

    table = PDFTable(
        page_number=1, table_index=0, data=[["Name", "Age", "City"], ["Alice", "30", "NY"], ["Bob", "25", "LA"]]
    )

    summary = parser._generate_table_summary_l0(table)
    assert "Page 1" in summary
    assert "Rows: 2" in summary
    assert "Headers: [Name, Age, City]" in summary
    assert "Data sample: Alice, 30, NY" in summary


def test_table_placeholder_format():
    """Test that table_format='placeholder' correctly replaces table with ID."""
    parser = PDFPlumberParser(table_format="placeholder")

    # Mock pdfplumber parts
    mock_page = MagicMock()
    mock_page.extract_text.return_value = "Context text"
    mock_page.extract_tables.return_value = [[["Col1", "Col2"], ["Val1", "Val2"]]]

    mock_pdf = MagicMock()
    # Mock the context manager behavior properly
    mock_pdf.__enter__.return_value = mock_pdf
    mock_pdf.pages = [mock_page]

    with patch("pdfplumber.open", return_value=mock_pdf), patch("pathlib.Path.exists", return_value=True):
        result = parser.parse_sync("fake.pdf")

        # Check text contains placeholder and L0 summary
        assert "[TABLE_CAPSULE: table_1_0]" in result.text
        assert "Structured Table on Page 1" in result.text
        # Markdown table should NOT be in the main text
        assert "| Col1 | Col2 |" not in result.text

        # But structured tables list should have it
        assert len(result.tables) == 1
        assert result.tables[0].id == "table_1_0"
        assert "| Col1 | Col2 |" in result.tables[0].markdown


@pytest.mark.asyncio
async def test_extract_pdf_content_with_tables():
    """Integration test for Table Capsules in extract_pdf_content."""
    with (
        patch("myrm_agent_harness.toolkits.file_parsers.pdf_content_extractor._extract_text_sync") as mock_text,
        patch("pathlib.Path.exists", return_value=True),
    ):
        from myrm_agent_harness.toolkits.file_parsers.base import PDFTable

        mock_table = PDFTable(page_number=1, table_index=0, data=[["X"]], id="t1", markdown="MD", summary_l0="L0")
        mock_text.return_value = ("[TABLE_CAPSULE: t1]", 1, [mock_table])

        # Mock other phases
        with (
            patch(
                "myrm_agent_harness.toolkits.file_parsers.pdf_content_extractor._extract_embedded_images_sync",
                return_value=[],
            ),
            patch(
                "myrm_agent_harness.toolkits.file_parsers.pdf_content_extractor._render_pages_sync", return_value=[]
            ),
        ):
            config = PDFExtractConfig(table_format="placeholder")
            result = await extract_pdf_content("fake.pdf", config)

            assert result.text == "[TABLE_CAPSULE: t1]"
            assert len(result.tables) == 1
            assert result.tables[0].summary_l0 == "L0"
