"""Page structure analyzer for intelligent snapshot optimization.


[INPUT]
- playwright.async_api::Page (POS: Playwright page object)

[OUTPUT]
- PageAnalyzer: page structure analyzer
- PageStructure: page structure info (dataclass)

[POS]
Lightweight page structure analyzer. Executes fast DOM analysis via page.evaluate(),
identifies major regions, counts elements, and generates smart optimization suggestions.
Includes report formatting, outputs YAML-style structured reports. Overhead ~15ms.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar

if TYPE_CHECKING:
    from playwright.async_api import Page

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PageStructure:
    """Page structure analysis result."""

    page_title: str
    page_url: str
    total_interactive_elements: int
    detected_regions: list[tuple[str, str, int]]
    recommended_selector: str
    estimated_savings: str


class PageAnalyzer:
    """Lightweight page structure analyzer.

    Responsibilities:
    1. Detect primary page regions (main, article, form, etc.)
    2. Count interactive elements
    3. Generate smart selector recommendations

    Performance: ~15ms
    """

    # Priority: semantic tags and common containers
    _SEMANTIC_TAGS: ClassVar[list[str]] = ["main", "article", "form", "nav"]
    _COMMON_IDS: ClassVar[list[str]] = ["app", "root", "main", "content", "container"]
    _COMMON_CLASSES: ClassVar[list[str]] = ["main", "content", "container", "app", "wrapper"]

    def __init__(self, page: Page) -> None:
        self._page = page

    async def analyze(self) -> PageStructure:
        """Fast page structure analysis.

        Returns:
            PageStructure with detected regions, recommended selectors, etc.

        Note:
            Runs a single page.evaluate() to minimize IPC round-trips.
            Only inspects DOM structure (not the full ARIA tree) for speed.
        """
        try:
            result = await self._page.evaluate(
                """
                () => {
                    // Count total interactive elements
                    const interactive = document.querySelectorAll(
                        'button, a, input, select, textarea, [role="button"], [role="link"], [onclick], [tabindex]'
                    );
                    const totalInteractive = interactive.length;

                    // Detect primary regions
                    const regions = [];

                    // Detect semantic tags
                    ['main', 'article', 'form', 'nav'].forEach(tag => {
                        const elements = document.querySelectorAll(tag);
                        elements.forEach((el, idx) => {
                            const interactiveCount = el.querySelectorAll(
                                'button, a, input, select, textarea, [role="button"], [role="link"]'
                            ).length;
                            const selector = elements.length === 1 ? tag : `${tag}:nth-of-type(${idx + 1})`;
                            const className = el.className ? `.${el.className.split(' ')[0]}` : '';
                            const finalSelector = className || selector;
                            if (interactiveCount > 0) {
                                regions.push([finalSelector, `<${tag}> region`, interactiveCount]);
                            }
                        });
                    });

                    // Detect common IDs
                    ['app', 'root', 'main', 'content', 'container'].forEach(id => {
                        const el = document.getElementById(id);
                        if (el) {
                            const interactiveCount = el.querySelectorAll(
                                'button, a, input, select, textarea, [role="button"], [role="link"]'
                            ).length;
                            if (interactiveCount > 0) {
                                regions.push([`#${id}`, `ID container`, interactiveCount]);
                            }
                        }
                    });

                    // Detect common classes (first match only)
                    ['main', 'content', 'container', 'app', 'wrapper'].forEach(cls => {
                        const elements = document.getElementsByClassName(cls);
                        if (elements.length > 0) {
                            const el = elements[0];
                            const interactiveCount = el.querySelectorAll(
                                'button, a, input, select, textarea, [role="button"], [role="link"]'
                            ).length;
                            if (interactiveCount > 0) {
                                regions.push([`.${cls}`, `Class container`, interactiveCount]);
                            }
                        }
                    });

                    return {
                        title: document.title,
                        url: window.location.href,
                        totalInteractive,
                        regions
                    };
                }
                """
            )

            # Parse result
            title = result.get("title", "Unknown")
            url = result.get("url", "")
            total_interactive = result.get("totalInteractive", 0)
            regions_raw = result.get("regions", [])

            # Deduplicate and sort (by interactive element count, descending)
            seen_selectors = set()
            regions = []
            for selector, desc, count in regions_raw:
                if selector not in seen_selectors:
                    seen_selectors.add(selector)
                    regions.append((selector, desc, count))

            regions.sort(key=lambda x: x[2], reverse=True)

            # Generate recommendation
            recommended, savings = self._compute_recommendation(total_interactive, regions)

            return PageStructure(
                page_title=title,
                page_url=url,
                total_interactive_elements=total_interactive,
                detected_regions=regions[:5],  # only return the top 5
                recommended_selector=recommended,
                estimated_savings=savings,
            )

        except Exception as exc:
            logger.warning(f"Page analysis failed: {exc}, using fallback")
            return PageStructure(
                page_title="Unknown",
                page_url="",
                total_interactive_elements=0,
                detected_regions=[],
                recommended_selector="",
                estimated_savings="0%",
            )

    def _compute_recommendation(self, total_interactive: int, regions: list[tuple[str, str, int]]) -> tuple[str, str]:
        """Compute the recommended selector and estimated savings.

        Args:
            total_interactive: Total interactive element count.
            regions: Detected primary regions [(selector, desc, count), ...].

        Returns:
            (recommended_selector, estimated_savings_percentage)
        """
        if not regions or total_interactive < 50:
            return "", "0%"

        best_region = regions[0]
        selector, _desc, count = best_region

        if count > 0:
            coverage = count / total_interactive
            savings_pct = int((1 - coverage) * 100)
            return selector, f"{savings_pct}%"

        return "", "0%"

    def format_report(self, structure: PageStructure) -> str:
        """Format the page structure analysis report.

        Args:
            structure: Page structure analysis result.

        Returns:
            A YAML-style report string.
        """
        output = ["=== PAGE STRUCTURE ===\n"]
        output.append(f"Title: {structure.page_title}")
        output.append(f"URL: {structure.page_url}")
        output.append(f"Total interactive elements: {structure.total_interactive_elements}\n")

        if structure.detected_regions:
            output.append("Main regions (by element count):")
            for selector, desc, count in structure.detected_regions:
                output.append(f"  - selector: {selector}")
                output.append(f"    type: {desc}")
                output.append(f"    interactive_elements: {count}")
        else:
            output.append("Main regions: None detected")

        output.append("")
        if structure.recommended_selector:
            output.append("RECOMMENDATION:")
            output.append(f"  Use: browser_snapshot(selector='{structure.recommended_selector}', scope='interactive')")
            output.append(f"  Estimated savings: {structure.estimated_savings}")
            savings_pct = int(structure.estimated_savings.rstrip("%")) / 100 if structure.estimated_savings else 0
            optimized_cost = int(structure.total_interactive_elements * 7 * (1 - savings_pct))
            output.append(
                f"  Current cost: ~{structure.total_interactive_elements * 7} tokens "
                f"(full page)\n  Optimized cost: ~{optimized_cost} tokens"
            )
        else:
            output.append("RECOMMENDATION:")
            output.append("  Page is small (<50 elements), browser_snapshot() with default params is optimal.")

        return "\n".join(output)
