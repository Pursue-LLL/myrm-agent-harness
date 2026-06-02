"""Benchmark compression performance."""

from __future__ import annotations

import time

import pytest

from myrm_agent_harness.runtime.compression import compress_content, decompress_content


class TestCompressionBenchmark:
    """Benchmark compression performance."""

    @pytest.fixture
    def html_content(self) -> str:
        """Generate realistic HTML content."""
        return (
            """
        <!DOCTYPE html>
        <html>
        <head>
            <title>Search Results</title>
            <meta charset="utf-8">
        </head>
        <body>
            <div class="container">
                <div class="result">
                    <h2>Result Title</h2>
                    <p>This is a search result with some content that describes the topic.</p>
                    <a href="https://example.com">Read more</a>
                </div>
            </div>
        </body>
        </html>
        """
            * 500
        )  # ~40KB

    @pytest.fixture
    def json_content(self) -> str:
        """Generate realistic JSON content."""
        return (
            '{"status": "success", "data": {"items": ['
            '{"id": 1, "name": "Item 1", "description": "Description for item 1"},'
            '{"id": 2, "name": "Item 2", "description": "Description for item 2"}'
            "]}}"
        ) * 200  # ~30KB

    def test_compression_speed_html(self, benchmark: pytest.fixture, html_content: str) -> None:
        """Benchmark HTML compression speed."""
        content_bytes = html_content.encode("utf-8")

        def compress() -> bytes:
            return compress_content(content_bytes)

        result = benchmark(compress)

        # Verify compression works
        assert len(result) < len(content_bytes)

        # Should be fast (<5ms for 40KB)
        assert benchmark.stats["mean"] < 0.005

    def test_compression_speed_json(self, benchmark: pytest.fixture, json_content: str) -> None:
        """Benchmark JSON compression speed."""
        content_bytes = json_content.encode("utf-8")

        def compress() -> bytes:
            return compress_content(content_bytes)

        result = benchmark(compress)

        # Verify compression works
        assert len(result) < len(content_bytes)

        # Should be fast (<5ms for 30KB)
        assert benchmark.stats["mean"] < 0.005

    def test_decompression_speed(self, benchmark: pytest.fixture, html_content: str) -> None:
        """Benchmark decompression speed."""
        content_bytes = html_content.encode("utf-8")
        compressed = compress_content(content_bytes)

        def decompress() -> bytes:
            return decompress_content(compressed)

        result = benchmark(decompress)

        # Verify decompression works
        assert result == content_bytes

        # Decompression should be faster than compression
        assert benchmark.stats["mean"] < 0.005

    def test_compression_ratio_html(self, html_content: str) -> None:
        """Test actual compression ratio for HTML."""
        content_bytes = html_content.encode("utf-8")
        compressed = compress_content(content_bytes)

        ratio = len(content_bytes) / len(compressed)

        # HTML should compress well (>3x)
        assert ratio > 3.0

        print(f"\nHTML compression: {len(content_bytes)} -> {len(compressed)} bytes (ratio: {ratio:.2f}x)")

    def test_compression_ratio_json(self, json_content: str) -> None:
        """Test actual compression ratio for JSON."""
        content_bytes = json_content.encode("utf-8")
        compressed = compress_content(content_bytes)

        ratio = len(content_bytes) / len(compressed)

        # JSON should compress well (>3x)
        assert ratio > 3.0

        print(f"\nJSON compression: {len(content_bytes)} -> {len(compressed)} bytes (ratio: {ratio:.2f}x)")

    def test_compression_levels_tradeoff(self) -> None:
        """Test compression level tradeoff (speed vs ratio)."""
        content = "A" * 50000  # 50KB
        content_bytes = content.encode("utf-8")

        results = []
        for level in [1, 3, 6, 9]:
            start = time.perf_counter()
            compressed = compress_content(content_bytes, level=level)
            duration = time.perf_counter() - start

            ratio = len(content_bytes) / len(compressed)
            results.append((level, duration, ratio))

        print("\nCompression level tradeoff:")
        for level, duration, ratio in results:
            print(f"  Level {level}: {duration * 1000:.2f}ms, ratio: {ratio:.2f}x")

        # Level 1 should be fastest
        assert results[0][1] <= results[-1][1]

        # Level 9 should have best ratio
        assert results[-1][2] >= results[0][2]
