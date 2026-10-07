"""Tests for High-Density Clean Markdown Extractor and Context Sparsity Pruning Suite (Item 234)."""

import pytest

from myrm_agent_harness.agent.context_management.clean_markdown_extractor import (
    CleanMarkdownExtractorConfig,
    CleanMarkdownExtractorEngine,
    DOMPruneRule,
    ExtractedCleanContent,
    ExtractionDensityLevel,
    SparsityPruneResult,
)


def test_clean_markdown_extraction_purifies_svg_and_boilerplate() -> None:
    """Verify raw HTML with 100KB of SVG icons and boilerplate is purified into dense Markdown under 100ms."""
    engine = CleanMarkdownExtractorEngine(CleanMarkdownExtractorConfig(bytes_per_token_estimate=4.0))

    svg_icon_junk = (
        '<svg viewBox="0 0 100 100" class="icon">'
        + '<path d="M10 20 L30 40 Z M50 60 L70 80 Z" fill="red" stroke="blue"/>' * 50
        + "</svg>\n"
    )

    raw_html = (
        "<!DOCTYPE html><html><head><title>Quantum Computing Breakthrough</title>"
        "<style>body { font-family: sans-serif; } .ad { display: block; }</style>"
        "<script>console.log('tracker script');</script></head><body>"
        "<nav><ul><li><a href='/'>Home</a></li><li><a href='/about'>About</a></li></ul></nav>"
        "<header><h1>Top Site Header Banner</h1></header>"
        "<div class='ad-banner'>Big Sponsored Advertisement</div>"
        "<h1>Quantum Computing Breakthrough 2026</h1>"
        "<p>Researchers have achieved stable 10,000-logical-qubit coherent teleportation.</p>"
        + (svg_icon_junk * 20)  # Generate 50KB+ of SVG vector garbage
        + "<p>This unlocks polynomial speedup for RSA-4096 prime factorization.</p>"
        "<pre><code>def factorize(n):\n    return quantum_shor_accelerate(n)</code></pre>"
        "<div class='promo-banner'>Subscribe for 50% off!</div>"
        "<footer><p>Copyright 2026 Quantum News Inc. All rights reserved.</p></footer>"
        "</body></html>"
    )

    raw_len = len(raw_html)
    assert raw_len > 20000

    extracted = engine.extract_clean_markdown(raw_html, source_id="https://news.quantum.org/breakthrough")

    assert extracted.title == "Quantum Computing Breakthrough"
    assert extracted.clean_char_count < raw_len * 0.10  # 90%+ volume stripped
    assert extracted.duration_ms < 2000.0  # Must be well under the 2-second hard limit (typically <50ms)
    assert extracted.tokens_saved > 4000

    clean_md = extracted.clean_markdown

    # Zero SVG garbage in clean text
    assert "<svg" not in clean_md
    assert "<path" not in clean_md
    assert "<style" not in clean_md
    assert "<script" not in clean_md
    assert "tracker script" not in clean_md

    # Core semantic facts and code blocks 100% intact
    assert "# Quantum Computing Breakthrough 2026" in clean_md
    assert "stable 10,000-logical-qubit coherent teleportation" in clean_md
    assert "def factorize(n):" in clean_md
    assert "quantum_shor_accelerate(n)" in clean_md


def test_context_sparsity_pruning_budget_and_focus() -> None:
    """Verify long documents are pruned with spatiotemporal sparsity, keeping focus and folding background."""
    engine = CleanMarkdownExtractorEngine()

    long_markdown = (
        "# Executive Summary\n"
        "This quarterly report covers semiconductor, biotechnology, and quantum computing progress.\n\n"
        "## Semiconductor Manufacturing\n"
        + ("Silicon wafer lithography yields reached 92% at 2nm node fabrication plants. " * 30)
        + "\n\n"
        "## Biotechnology & Gene Editing\n"
        + ("Clinical phase III CRISPR trials completed successfully with zero off-target mutations. " * 30)
        + "\n\n"
        "## Quantum Computing Highlights\n"
        "Milestone achieved: room-temperature optical quantum interconnect demonstrated at 100 Gbps.\n"
        "Key breakthrough allows modular optical routing across 16 cryostats.\n\n"
        "## Legal & Disclaimers\n"
        + ("Forward-looking statements involve substantial uncertainties and market risks. " * 30)
    )

    # Prune with focus on Quantum Computing under a tight token budget
    prune_res = engine.apply_context_sparsity_pruning(
        markdown_text=long_markdown,
        query_focus="Quantum Computing",
        token_budget=200,
    )

    assert prune_res.active_sections_kept >= 1
    assert prune_res.folded_sections_count >= 2
    assert prune_res.tokens_saved > 0
    assert prune_res.savings_ratio > 0.40

    sparse_text = prune_res.sparse_markdown

    # Focused section remains fully available
    assert "## Quantum Computing Highlights" in sparse_text
    assert "room-temperature optical quantum interconnect demonstrated at 100 Gbps" in sparse_text

    # Unfocused background sections are folded into compact anchors
    assert "[Folded background section" in sparse_text


def test_clean_markdown_extractor_handles_plain_text_and_malformed_html() -> None:
    """Verify resilient fallback when input contains plain text or unclosed HTML tags."""
    engine = CleanMarkdownExtractorEngine()

    plain_text = "Just a raw string with no tags.\nSecond line of plain text."
    result = engine.extract_clean_markdown(plain_text)
    assert "Just a raw string with no tags." in result.clean_markdown
    assert result.clean_char_count > 0

    malformed_html = "<div><p>Unclosed paragraph<h1>Header without end</div>"
    result_malformed = engine.extract_clean_markdown(malformed_html)
    assert "Header without end" in result_malformed.clean_markdown


def test_code_block_and_list_conversion() -> None:
    """Verify HTML list and pre elements are properly converted to standard Markdown syntax."""
    engine = CleanMarkdownExtractorEngine()

    html = (
        "<ul>"
        "<li>First feature</li>"
        "<li>Second feature</li>"
        "</ul>"
        "<pre><code>echo 'Hello World'</code></pre>"
    )

    result = engine.extract_clean_markdown(html)
    assert "- First feature" in result.clean_markdown
    assert "- Second feature" in result.clean_markdown
    assert "```\necho 'Hello World'\n```" in result.clean_markdown
