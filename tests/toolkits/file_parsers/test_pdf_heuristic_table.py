"""Unit tests for PDF heuristic table extractor."""

from myrm_agent_harness.toolkits.file_parsers.pdf_heuristic_table import extract_heuristic_tables_from_words


def test_extract_heuristic_tables_with_wrapped_text():
    """Test that wrapped text within a cell is merged correctly into a single logical row."""
    # Simulate words that belong to a single row but are split across two lines due to wrapping
    words = [
        # Line 1: Main row content
        {"text": "Software", "x0": 50, "x1": 85, "top": 100, "bottom": 110},
        {"text": "License", "x0": 90, "x1": 130, "top": 100, "bottom": 110},
        {"text": "USD", "x0": 200, "x1": 230, "top": 100, "bottom": 110},
        {"text": "15,000", "x0": 300, "x1": 350, "top": 100, "bottom": 110},
        # Line 2: Wrapped text from the first column, other columns empty
        {"text": "Renewal", "x0": 50, "x1": 85, "top": 112, "bottom": 122},
        {"text": "Fee", "x0": 90, "x1": 120, "top": 112, "bottom": 122},
        # Line 3: Next valid row of data (should not be merged with Line 2)
        {"text": "Server", "x0": 50, "x1": 90, "top": 130, "bottom": 140},
        {"text": "Maintenance", "x0": 95, "x1": 160, "top": 130, "bottom": 140},
        {"text": "USD", "x0": 200, "x1": 230, "top": 130, "bottom": 140},
        {"text": "2,000", "x0": 300, "x1": 340, "top": 130, "bottom": 140},
    ]

    tables = extract_heuristic_tables_from_words(words, page_width=612.0)

    # We expect 1 table
    assert len(tables) == 1

    table_data, _bbox = tables[0]

    # We expect exactly 2 logical rows after merging wrapped text
    assert len(table_data) == 2

    # Row 1 should have merged Line 1 and Line 2
    assert table_data[0][0] == "Software License Renewal Fee"
    assert table_data[0][1] == "USD"
    assert table_data[0][2] == "15,000"

    # Row 2 should be the server maintenance line
    assert table_data[1][0] == "Server Maintenance"
    assert table_data[1][1] == "USD"
    assert table_data[1][2] == "2,000"


def test_extract_heuristic_tables_no_over_merging():
    """Test that distinct dense rows are NOT incorrectly merged."""
    words = [
        # Line 1
        {"text": "Item", "x0": 50, "x1": 80, "top": 100, "bottom": 110},
        {"text": "A", "x0": 85, "x1": 95, "top": 100, "bottom": 110},
        {"text": "1", "x0": 200, "x1": 210, "top": 100, "bottom": 110},
        {"text": "100.00", "x0": 300, "x1": 340, "top": 100, "bottom": 110},
        # Line 2 (Very close to Line 1, but has full columns, so it's a separate row)
        {"text": "Item", "x0": 50, "x1": 80, "top": 111, "bottom": 121},
        {"text": "B", "x0": 85, "x1": 95, "top": 111, "bottom": 121},
        {"text": "2", "x0": 200, "x1": 210, "top": 111, "bottom": 121},
        {"text": "200.00", "x0": 300, "x1": 340, "top": 111, "bottom": 121},
    ]

    tables = extract_heuristic_tables_from_words(words, page_width=612.0)

    assert len(tables) == 1
    table_data, _ = tables[0]

    # Should be 2 distinct rows because they both have values in the columns, indicating separate records
    assert len(table_data) == 2
    assert table_data[0] == ["Item A", "1", "100.00"]
    assert table_data[1] == ["Item B", "2", "200.00"]


def test_extract_heuristic_tables_cjk_no_space():
    """Test that CJK characters are merged without spaces, while others use spaces."""
    words = [
        # Line 1: Main row content (Chinese)
        {"text": "营业", "x0": 50, "x1": 70, "top": 100, "bottom": 110},
        {"text": "100", "x0": 200, "x1": 220, "top": 100, "bottom": 110},
        {"text": "A", "x0": 300, "x1": 310, "top": 100, "bottom": 110},
        # Line 2: Wrapped text from the first column
        {"text": "收入", "x0": 50, "x1": 70, "top": 115, "bottom": 125},
        # Dummy line to make it a table region > 1
        {"text": "利润", "x0": 50, "x1": 70, "top": 130, "bottom": 140},
        {"text": "200", "x0": 200, "x1": 220, "top": 130, "bottom": 140},
        {"text": "B", "x0": 300, "x1": 310, "top": 130, "bottom": 140},
    ]

    tables = extract_heuristic_tables_from_words(words, page_width=612.0)
    
    assert len(tables) == 1
    table_data, _ = tables[0]
    
    # "营业" + "收入" should become "营业收入" (no space)
    assert len(table_data) == 2
    assert table_data[0][0] == "营业收入"
    assert table_data[0][1] == "100"


def test_extract_heuristic_tables_dynamic_gap_large_font():
    """Test that dynamic gap works for large fonts (e.g. PPT exported PDFs) where gap > 12.0."""
    words = [
        # Line 1: Main row content (Large Font, 30pt height)
        {"text": "Annual", "x0": 50, "x1": 150, "top": 100, "bottom": 130},
        {"text": "2024", "x0": 300, "x1": 350, "top": 100, "bottom": 130},
        {"text": "Q1", "x0": 400, "x1": 450, "top": 100, "bottom": 130},
        # Line 2: Wrapped text (Gap is 148 - 130 = 18.0, which > 12.0, but < 30 * 1.5)
        {"text": "Revenue", "x0": 50, "x1": 150, "top": 148, "bottom": 178},
        # Line 3: Dummy line
        {"text": "Net", "x0": 50, "x1": 100, "top": 190, "bottom": 220},
        {"text": "2025", "x0": 300, "x1": 350, "top": 190, "bottom": 220},
        {"text": "Q2", "x0": 400, "x1": 450, "top": 190, "bottom": 220},
    ]

    tables = extract_heuristic_tables_from_words(words, page_width=612.0)
    
    assert len(tables) == 1
    table_data, _ = tables[0]
    
    # Should merge successfully because 18.0 < 45.0 (30 * 1.5)
    assert len(table_data) == 2
    assert table_data[0][0] == "Annual Revenue"
    assert table_data[0][1] == "2024"
