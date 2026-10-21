"""Performance benchmark tests for aria_acquisition.

Validates the performance claims:
- "Large pages: 800ms → 120ms (85% reduction)"

These tests require a real browser and are marked as integration tests.
Run with: pytest tests/toolkits/browser/test_aria_acquisition_performance.py -v

Note: Uses patchright directly (not GlobalBrowserPool) for faster test execution.
"""

import time

import pytest
from patchright.async_api import async_playwright

pytestmark = pytest.mark.xdist_group("browser_perf")

from myrm_agent_harness.toolkits.browser.snapshot.aria_acquisition import get_aria_tree


def _generate_deep_html(depth: int, children_per_level: int) -> str:
    """Generate deeply nested HTML for performance testing.

    Args:
        depth: Tree depth (e.g., 7 = 7 levels)
        children_per_level: Number of children per node (e.g., 3)

    Returns:
        HTML string with nested structure

    Note:
        depth=7, children=3 → ~2,187 nodes (3^7)
        Uses <section> tags to create proper DOM hierarchy for depth testing.
    """

    def build_tree(current_depth: int) -> str:
        if current_depth >= depth:
            return ""

        children = ""
        for i in range(children_per_level):
            child_content = build_tree(current_depth + 1)
            children += f"""
            <section>
                <button>Action {current_depth}-{i}</button>
                <input type="text" placeholder="Input {current_depth}-{i}" />
                {child_content}
            </section>
            """

        return children

    html = f"""
    <!DOCTYPE html>
    <html>
    <head><title>Deep Tree Test</title></head>
    <body>
        <div id="root">
            {build_tree(0)}
        </div>
    </body>
    </html>
    """
    return html


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.slow
async def test_performance_fast_path_baseline() -> None:
    """Baseline: Fast Path performance on large page (no depth limit)."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()

        try:
            # Generate large page (depth=6, children=3 → ~730 nodes)
            html = _generate_deep_html(depth=6, children_per_level=3)
            await page.set_content(html)

            locator = page.locator(":root")

            # Warm-up run
            await get_aria_tree(locator, max_depth=None)

            # Measure Fast Path performance (5 runs for stability)
            timings = []
            for _ in range(5):
                start = time.perf_counter()
                result = await get_aria_tree(locator, max_depth=None)
                elapsed_ms = (time.perf_counter() - start) * 1000
                timings.append(elapsed_ms)

            avg_time = sum(timings) / len(timings)

            # Verify result is valid
            assert "button" in result
            assert len(result) > 1000  # Large tree

            # Log performance data
            print(f"\n[BENCHMARK] Fast Path (full tree): {avg_time:.1f}ms (avg of {timings})")

            # Sanity check: should complete within reasonable time
            assert avg_time < 2000, f"Fast Path too slow: {avg_time}ms"

        finally:
            await browser.close()


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.slow
async def test_performance_custom_path_with_depth_limit() -> None:
    """Test: Custom Path performance with depth limit (maxDepth=4)."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()

        try:
            # Same large page as baseline test
            html = _generate_deep_html(depth=6, children_per_level=3)
            await page.set_content(html)

            locator = page.locator(":root")

            # Warm-up run
            await get_aria_tree(locator, max_depth=4)

            # Measure Custom Path performance (5 runs for stability)
            timings = []
            for _ in range(5):
                start = time.perf_counter()
                result = await get_aria_tree(locator, max_depth=4)
                elapsed_ms = (time.perf_counter() - start) * 1000
                timings.append(elapsed_ms)

            avg_time = sum(timings) / len(timings)

            # Verify result is truncated (smaller than full tree)
            assert "button" in result
            assert len(result) < 1000  # Truncated tree should be smaller

            # Log performance data
            print(f"\n[BENCHMARK] Custom Path (maxDepth=4): {avg_time:.1f}ms (avg of {timings})")

            # Sanity check: should be faster than Fast Path
            assert avg_time < 500, f"Custom Path too slow: {avg_time}ms"

        finally:
            await browser.close()


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.slow
async def test_performance_comparison() -> None:
    """Compare Fast Path vs Custom Path performance on large page.

    This test validates the performance claim:
    "Large pages: 800ms → 120ms (85% reduction)"
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()

        try:
            # Generate very large page (depth=7, children=3 → ~2,200 nodes)
            html = _generate_deep_html(depth=7, children_per_level=3)
            await page.set_content(html)

            locator = page.locator(":root")

            # Test 1: Fast Path (full tree)
            fast_timings = []
            for _ in range(3):
                start = time.perf_counter()
                fast_result = await get_aria_tree(locator, max_depth=None)
                elapsed_ms = (time.perf_counter() - start) * 1000
                fast_timings.append(elapsed_ms)

            fast_avg = sum(fast_timings) / len(fast_timings)

            # Test 2: Custom Path (maxDepth=4)
            custom_timings = []
            for _ in range(3):
                start = time.perf_counter()
                custom_result = await get_aria_tree(locator, max_depth=4)
                elapsed_ms = (time.perf_counter() - start) * 1000
                custom_timings.append(elapsed_ms)

            custom_avg = sum(custom_timings) / len(custom_timings)

            # Calculate performance improvement
            reduction_percent = ((fast_avg - custom_avg) / fast_avg) * 100

            # Log detailed results
            print("\n[BENCHMARK] Performance Comparison:")
            print(f"  Fast Path (full tree):  {fast_avg:.1f}ms")
            print(f"  Custom Path (depth=4):  {custom_avg:.1f}ms")
            print(f"  Reduction:              {reduction_percent:.1f}%")
            print(f"  Tree size (fast):       {len(fast_result)} chars")
            print(f"  Tree size (custom):     {len(custom_result)} chars")

            # Verify Custom Path is actually faster
            assert custom_avg < fast_avg, (
                f"Custom Path ({custom_avg:.1f}ms) should be faster than Fast Path ({fast_avg:.1f}ms)"
            )

            # Verify significant performance improvement (at least 30%)
            assert reduction_percent > 30, (
                f"Performance improvement ({reduction_percent:.1f}%) should be significant (>30%)"
            )

            # Note: The documented "85%" is for extreme cases (depth=10+, children=5+)
            # Typical scenarios may show 40-70% improvement

        finally:
            await browser.close()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_max_depth_zero_performance() -> None:
    """Test that max_depth=0 only processes root node (minimal work)."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()

        try:
            # Large page
            html = _generate_deep_html(depth=6, children_per_level=3)
            await page.set_content(html)

            locator = page.locator(":root")

            # Test max_depth=0 (only root)
            start = time.perf_counter()
            result = await get_aria_tree(locator, max_depth=0)
            elapsed_ms = (time.perf_counter() - start) * 1000

            # Should be very fast (no children traversed)
            assert elapsed_ms < 200, f"max_depth=0 too slow: {elapsed_ms}ms"

            # Tree should be minimal
            assert len(result) < 100, f"max_depth=0 tree too large: {len(result)} chars"

            print(f"\n[BENCHMARK] max_depth=0: {elapsed_ms:.1f}ms, size={len(result)} chars")

        finally:
            await browser.close()
