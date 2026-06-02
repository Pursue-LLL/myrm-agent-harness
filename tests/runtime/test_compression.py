"""Tests for compression utilities."""

from __future__ import annotations

import gzip

import pytest

from myrm_agent_harness.runtime.compression import (
    compress_content,
    decompress_content,
    estimate_compression_ratio,
    get_compressed_size,
    should_compress,
)


class TestCompression:
    """Test compression utilities."""

    def test_compress_string(self) -> None:
        """Test compressing string content."""
        content = "Hello World" * 1000
        compressed = compress_content(content)

        assert isinstance(compressed, bytes)
        assert len(compressed) < len(content)

        # Verify it's valid gzip
        decompressed = gzip.decompress(compressed)
        assert decompressed.decode("utf-8") == content

    def test_compress_bytes(self) -> None:
        """Test compressing bytes content."""
        content = b"Hello World" * 1000
        compressed = compress_content(content)

        assert isinstance(compressed, bytes)
        assert len(compressed) < len(content)

        decompressed = gzip.decompress(compressed)
        assert decompressed == content

    def test_compress_with_level(self) -> None:
        """Test compression with different levels."""
        content = "A" * 10000

        # Level 1 (fast, lower ratio)
        compressed_1 = compress_content(content, level=1)

        # Level 9 (slow, higher ratio)
        compressed_9 = compress_content(content, level=9)

        # Higher level should produce smaller output
        assert len(compressed_9) <= len(compressed_1)

    def test_decompress(self) -> None:
        """Test decompression."""
        original = "Hello World" * 1000
        compressed = compress_content(original)
        decompressed = decompress_content(compressed)

        assert decompressed.decode("utf-8") == original

    def test_decompress_invalid_data(self) -> None:
        """Test decompression with invalid data."""
        with pytest.raises(gzip.BadGzipFile):
            decompress_content(b"not gzip data")

    def test_should_compress_below_threshold(self) -> None:
        """Test should_compress with small files."""
        assert not should_compress(5000)  # 5KB
        assert not should_compress(10240)  # Exactly 10KB (not greater)

    def test_should_compress_above_threshold(self) -> None:
        """Test should_compress with large files."""
        assert should_compress(10241)  # 10KB + 1 byte
        assert should_compress(20000)  # 20KB
        assert should_compress(1024000)  # 1MB

    def test_should_compress_custom_threshold(self) -> None:
        """Test should_compress with custom threshold."""
        assert not should_compress(5000, threshold=10000)
        assert should_compress(5000, threshold=4000)

    def test_estimate_compression_ratio(self) -> None:
        """Test compression ratio estimation."""
        # High repetition content
        high_rep = "A" * 10000
        ratio_high = estimate_compression_ratio(high_rep)
        assert ratio_high > 3.0

        # Low repetition content (random data)
        import random
        import string

        low_rep = "".join(random.choices(string.ascii_letters + string.digits, k=10000))
        ratio_low = estimate_compression_ratio(low_rep)
        # Estimation is conservative, may return higher values
        assert ratio_low >= 1.0

    def test_estimate_compression_ratio_empty(self) -> None:
        """Test compression ratio estimation with empty content."""
        ratio = estimate_compression_ratio("")
        assert ratio == 1.0

    def test_get_compressed_size(self) -> None:
        """Test getting compressed size."""
        content = "Hello World" * 1000
        compressed_size = get_compressed_size(content)

        # Verify it matches actual compression
        actual_compressed = compress_content(content)
        assert compressed_size == len(actual_compressed)

    def test_compression_roundtrip(self) -> None:
        """Test full compression/decompression roundtrip."""
        test_cases = [
            "Simple text",
            "A" * 10000,  # High repetition
            '{"key": "value"}' * 1000,  # JSON
            "<html><body>Content</body></html>" * 500,  # HTML
            "Mixed 中文 English 日本語 content",  # Unicode
        ]

        for original in test_cases:
            compressed = compress_content(original)
            decompressed = decompress_content(compressed)
            assert decompressed.decode("utf-8") == original

    def test_compression_ratio_realistic(self) -> None:
        """Test compression ratio with realistic content."""
        # HTML content (typical web search result)
        html = (
            """
        <!DOCTYPE html>
        <html>
        <head><title>Test</title></head>
        <body>
            <div class="content">
                <p>This is a test paragraph.</p>
                <p>This is another test paragraph.</p>
            </div>
        </body>
        </html>
        """
            * 100
        )

        compressed = compress_content(html)
        ratio = len(html) / len(compressed)

        # HTML should compress well (3-5x)
        assert ratio > 3.0

        # JSON content (typical API response)
        json_content = '{"status": "success", "data": {"items": []}}' * 500

        compressed_json = compress_content(json_content)
        ratio_json = len(json_content) / len(compressed_json)

        # JSON should compress well (3-5x)
        assert ratio_json > 3.0
