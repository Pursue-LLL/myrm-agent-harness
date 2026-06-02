"""Benchmark compression with realistic content types.

Tests compression performance with actual HTML, JSON, and code content
to provide accurate performance data for documentation.
"""

from __future__ import annotations

import time

from myrm_agent_harness.runtime.compression import compress_content


def generate_realistic_html(size_kb: int) -> str:
    """Generate realistic HTML content."""
    base_html = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Search Results</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 20px; }
        .result { margin-bottom: 20px; padding: 15px; border: 1px solid #ddd; }
        .title { font-size: 18px; font-weight: bold; color: #1a0dab; }
        .snippet { color: #545454; line-height: 1.6; }
        .url { color: #006621; font-size: 14px; }
    </style>
</head>
<body>
    <h1>Search Results</h1>
"""
    result_template = """
    <div class="result">
        <div class="title">Result Title {idx}: Understanding {topic}</div>
        <div class="url">https://example.com/article-{idx}</div>
        <div class="snippet">
            This is a comprehensive guide about {topic}. It covers various aspects
            including implementation details, best practices, and common pitfalls.
            The article provides code examples and real-world use cases to help
            developers understand the concepts better. Updated on {date}.
        </div>
    </div>
"""
    footer = """
</body>
</html>
"""

    topics = ["Python", "JavaScript", "Docker", "Kubernetes", "AI", "Database"]
    dates = ["2024-01-15", "2024-02-20", "2024-03-10", "2024-04-05"]

    content = base_html
    idx = 0
    while len(content) < size_kb * 1024:
        topic = topics[idx % len(topics)]
        date = dates[idx % len(dates)]
        content += result_template.format(idx=idx, topic=topic, date=date)
        idx += 1

    content += footer
    return content[: size_kb * 1024]


def generate_realistic_json(size_kb: int) -> str:
    """Generate realistic JSON content."""
    base_json = '{"results": ['
    item_template = """
    {{
        "id": {idx},
        "name": "Item {idx}",
        "description": "This is a detailed description of item {idx}",
        "price": {price},
        "category": "{category}",
        "tags": ["tag1", "tag2", "tag3"],
        "metadata": {{
            "created_at": "2024-03-{day:02d}T10:00:00Z",
            "updated_at": "2024-03-{day:02d}T15:30:00Z",
            "author": "user{author_id}"
        }},
        "attributes": {{
            "color": "{color}",
            "size": "{size}",
            "weight": {weight}
        }}
    }}"""

    categories = ["Electronics", "Books", "Clothing", "Food", "Toys"]
    colors = ["Red", "Blue", "Green", "Black", "White"]
    sizes = ["Small", "Medium", "Large", "XL"]

    content = base_json
    idx = 0
    while len(content) < size_kb * 1024:
        if idx > 0:
            content += ","
        category = categories[idx % len(categories)]
        color = colors[idx % len(colors)]
        size = sizes[idx % len(sizes)]
        content += item_template.format(
            idx=idx,
            price=10.0 + (idx % 100),
            category=category,
            day=(idx % 28) + 1,
            author_id=idx % 10,
            color=color,
            size=size,
            weight=0.5 + (idx % 50) * 0.1,
        )
        idx += 1

    content += "]}"
    return content[: size_kb * 1024]


def generate_realistic_code(size_kb: int) -> str:
    """Generate realistic Python code."""
    base_code = '''"""Module for data processing."""

from typing import Any, Dict, List
import json
import logging

logger = logging.getLogger(__name__)

'''
    function_template = '''
def process_data_{idx}(data: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Process data item {idx}.

    Args:
        data: Input data list

    Returns:
        Processed result dictionary
    """
    result = {{}}
    try:
        for item in data:
            if "id" in item:
                result[item["id"]] = {{
                    "value": item.get("value", 0),
                    "status": "processed",
                    "timestamp": item.get("timestamp"),
                }}
        logger.info("Processed %d items", len(result))
        return result
    except Exception as e:
        logger.error("Error processing data: %s", e)
        return {{"error": str(e)}}

'''

    content = base_code
    idx = 0
    while len(content) < size_kb * 1024:
        content += function_template.format(idx=idx)
        idx += 1

    return content[: size_kb * 1024]


def benchmark_realistic_content() -> None:
    """Benchmark compression with realistic content."""
    print("=" * 80)
    print("Realistic Content Compression Benchmark")
    print("=" * 80)
    print()

    test_cases = [
        ("HTML (30KB)", generate_realistic_html(30)),
        ("HTML (200KB)", generate_realistic_html(200)),
        ("JSON (30KB)", generate_realistic_json(30)),
        ("JSON (200KB)", generate_realistic_json(200)),
        ("Code (30KB)", generate_realistic_code(30)),
        ("Code (200KB)", generate_realistic_code(200)),
    ]

    levels_to_test = [1, 6, 9]

    for test_name, content in test_cases:
        print(f"\n{test_name} ({len(content):,} bytes):")
        print("-" * 60)

        results = {}
        for level in levels_to_test:
            # Warmup
            for _ in range(3):
                compress_content(content, level=level)

            # Benchmark
            iterations = 10
            start = time.perf_counter()
            compressed_sizes = []
            for _ in range(iterations):
                compressed = compress_content(content, level=level)
                compressed_sizes.append(len(compressed))
            duration = time.perf_counter() - start

            avg_time = duration / iterations * 1000  # ms
            avg_size = sum(compressed_sizes) / len(compressed_sizes)
            compression_ratio = len(content) / avg_size

            results[level] = {
                "time_ms": avg_time,
                "size": avg_size,
                "ratio": compression_ratio,
            }

            print(f"  Level {level}: {avg_time:.3f}ms, {avg_size:,.0f} bytes, ratio: {compression_ratio:.2f}x")

        # Calculate speedup and compression improvement
        if 1 in results and 6 in results:
            speedup_1_vs_6 = results[6]["time_ms"] / results[1]["time_ms"]
            ratio_diff_1_vs_6 = (results[6]["ratio"] - results[1]["ratio"]) / results[1]["ratio"] * 100
            print(f"\n  Speed: Level 1 is {speedup_1_vs_6:.2f}x faster than Level 6")
            print(f"  Compression: Level 6 is {ratio_diff_1_vs_6:.1f}% better than Level 1")

        if 6 in results and 9 in results:
            ratio_improvement = (results[9]["ratio"] - results[6]["ratio"]) / results[6]["ratio"] * 100
            time_overhead = (results[9]["time_ms"] - results[6]["time_ms"]) / results[6]["time_ms"] * 100
            print(f"  Compression: Level 9 is {ratio_improvement:.1f}% better than Level 6")
            print(f"  Time cost: Level 9 is {time_overhead:.1f}% slower than Level 6")

    print("\n" + "=" * 80)
    print("Summary: Realistic content shows moderate compression differences")
    print("between levels, unlike highly repetitive synthetic data.")
    print("=" * 80)


if __name__ == "__main__":
    benchmark_realistic_content()
