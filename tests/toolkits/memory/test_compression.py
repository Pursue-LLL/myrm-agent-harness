"""Test memory payload compression."""

from __future__ import annotations

import gzip

import pytest

from myrm_agent_harness.toolkits.memory.compression import (
    compress_if_needed,
    compress_payload,
    decompress_payload,
    get_compression_stats,
    is_compressed,
)


def test_compress_payload_below_threshold() -> None:
    """Small payloads should not be compressed."""
    small_text = "Hello world!"
    result = compress_payload(small_text, threshold=100)

    assert not is_compressed(result)
    assert result == small_text.encode("utf-8")


def test_compress_payload_above_threshold() -> None:
    """Large payloads should be compressed."""
    large_text = "A" * 200_000
    result = compress_payload(large_text, threshold=100 * 1024)

    assert is_compressed(result)
    assert len(result) < len(large_text.encode("utf-8"))


def test_decompress_payload_compressed() -> None:
    """Decompress gzip-compressed data."""
    original = "This is a test message." * 10_000
    compressed = compress_payload(original, threshold=1024)

    decompressed = decompress_payload(compressed)

    assert decompressed == original


def test_decompress_payload_uncompressed() -> None:
    """Decompress uncompressed data (passthrough)."""
    original = "Hello world!"
    raw_bytes = original.encode("utf-8")

    decompressed = decompress_payload(raw_bytes)

    assert decompressed == original


def test_decompress_payload_empty() -> None:
    """Empty payload should return empty string."""
    assert decompress_payload(b"") == ""


def test_decompress_payload_corrupted() -> None:
    """Corrupted gzip data should raise exception."""
    corrupted = b"\x1f\x8b\x08\x00\x00\x00\x00\x00CORRUPTED"

    with pytest.raises((gzip.BadGzipFile, EOFError)):
        decompress_payload(corrupted)


def test_is_compressed() -> None:
    """Magic byte detection should identify gzip data."""
    compressed = gzip.compress(b"test")
    uncompressed = b"test"

    assert is_compressed(compressed)
    assert not is_compressed(uncompressed)


def test_compress_if_needed_none() -> None:
    """None input should return None."""
    assert compress_if_needed(None) is None


def test_compress_if_needed_already_compressed() -> None:
    """Already compressed data should not be re-compressed."""
    compressed = gzip.compress(b"test" * 50_000)
    result = compress_if_needed(compressed, threshold=1024)

    assert result == compressed


def test_compress_if_needed_string() -> None:
    """String input should be compressed if above threshold."""
    large_string = "X" * 200_000
    result = compress_if_needed(large_string, threshold=100 * 1024)

    assert result is not None
    assert is_compressed(result)


def test_get_compression_stats() -> None:
    """Compression stats should calculate ratio and savings."""
    stats = get_compression_stats(original_size=100_000, compressed_size=20_000)

    assert stats["ratio"] == 0.2
    assert stats["reduction_pct"] == 80.0
    assert stats["savings_bytes"] == 80_000


def test_roundtrip_large_conversation() -> None:
    """Full roundtrip: compress → store → retrieve → decompress."""
    conversation = "User: How do I optimize Python?\n" + "AI: Use caching strategies.\n" * 5000

    compressed = compress_payload(conversation, threshold=10_000)
    assert is_compressed(compressed)
    assert len(compressed) < len(conversation.encode("utf-8"))

    decompressed = decompress_payload(compressed)
    assert decompressed == conversation
