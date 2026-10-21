"""Extreme performance test to validate maxDepth optimization claims."""

import asyncio
import time

from patchright.async_api import async_playwright

from myrm_agent_harness.toolkits.browser.snapshot.aria_acquisition import get_aria_tree


def _generate_large_html(depth: int, children: int) -> str:
    """Generate very large nested HTML."""

    def build(current_depth: int) -> str:
        if current_depth >= depth:
            return ""

        children_html = ""
        for i in range(children):
            child = build(current_depth + 1)
            children_html += f"""
            <section>
                <button>Action {current_depth}-{i}</button>
                <input type="text" placeholder="Input {current_depth}-{i}" />
                <a href="#">Link {current_depth}-{i}</a>
                {child}
            </section>
            """
        return children_html

    return f"""
    <!DOCTYPE html>
    <html>
    <head><title>Large Page Test</title></head>
    <body><div id="root">{build(0)}</div></body>
    </html>
    """


async def main():
    """Run extreme performance tests."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()

        # Scenario 1: Moderate depth (depth=7, children=3)
        print("=" * 60)
        print("SCENARIO 1: Moderate depth (depth=7, children=3)")
        print("=" * 60)
        html = _generate_large_html(depth=7, children=3)
        print(f"HTML size: {len(html):,} chars")
        await page.set_content(html)
        locator = page.locator(":root")

        # Fast Path
        timings = []
        for _ in range(5):
            start = time.perf_counter()
            result = await get_aria_tree(locator, max_depth=None)
            elapsed_ms = (time.perf_counter() - start) * 1000
            timings.append(elapsed_ms)
        fast_avg = sum(timings) / len(timings)
        fast_size = len(result)

        # Custom Path (maxDepth=4)
        timings = []
        for _ in range(5):
            start = time.perf_counter()
            result = await get_aria_tree(locator, max_depth=4)
            elapsed_ms = (time.perf_counter() - start) * 1000
            timings.append(elapsed_ms)
        custom_avg = sum(timings) / len(timings)
        custom_size = len(result)

        reduction_1 = ((fast_avg - custom_avg) / fast_avg) * 100
        print(f"Fast Path:   {fast_avg:.1f}ms ({fast_size:,} chars)")
        print(f"Custom Path: {custom_avg:.1f}ms ({custom_size:,} chars)")
        print(f"Reduction:   {reduction_1:.1f}%")

        # Scenario 2: Large depth (depth=8, children=3)
        print("\n" + "=" * 60)
        print("SCENARIO 2: Large depth (depth=8, children=3)")
        print("=" * 60)
        html = _generate_large_html(depth=8, children=3)
        print(f"HTML size: {len(html):,} chars")
        await page.set_content(html)
        locator = page.locator(":root")

        # Fast Path
        timings = []
        for _ in range(5):
            start = time.perf_counter()
            result = await get_aria_tree(locator, max_depth=None)
            elapsed_ms = (time.perf_counter() - start) * 1000
            timings.append(elapsed_ms)
        fast_avg = sum(timings) / len(timings)
        fast_size = len(result)

        # Custom Path (maxDepth=4)
        timings = []
        for _ in range(5):
            start = time.perf_counter()
            result = await get_aria_tree(locator, max_depth=4)
            elapsed_ms = (time.perf_counter() - start) * 1000
            timings.append(elapsed_ms)
        custom_avg = sum(timings) / len(timings)
        custom_size = len(result)

        reduction_2 = ((fast_avg - custom_avg) / fast_avg) * 100
        print(f"Fast Path:   {fast_avg:.1f}ms ({fast_size:,} chars)")
        print(f"Custom Path: {custom_avg:.1f}ms ({custom_size:,} chars)")
        print(f"Reduction:   {reduction_2:.1f}%")

        # Summary
        print("\n" + "=" * 60)
        print("SUMMARY")
        print("=" * 60)
        print(f"Scenario 1 (depth=7): {reduction_1:.1f}% reduction")
        print(f"Scenario 2 (depth=8): {reduction_2:.1f}% reduction")
        print(f"\nConclusion: maxDepth optimization shows {max(reduction_1, reduction_2):.1f}% max reduction")

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
