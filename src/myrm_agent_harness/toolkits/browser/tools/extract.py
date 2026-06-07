"""browser_extract tool for content extraction.

[INPUT]
- (none)

[OUTPUT]
- create_extract_tool: Create browser_extract tool bound to session.

[POS]
browser_extract tool for content extraction.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from langchain.tools import tool
from pydantic import BaseModel, Field

from .common import mark_untrusted

if TYPE_CHECKING:
    from ..session import BrowserSession


def create_extract_tool(session: BrowserSession):
    """Create browser_extract tool bound to session."""

    class ExtractInput(BaseModel):
        mode: str = Field(
            default="text",
            description="'text' for readable page text (precise, low-cost), "
            "'screenshot' for JPEG visual capture (layout verification only, ~850 tokens), "
            "'diff_fast' for quick visual change detection (~2ms, perceptual hash similarity), "
            "'diff_accurate' for detailed visual analysis (~100ms, pixel-level mismatch + diff image). "
            "Prefer 'text' for reading content; use 'screenshot' for visual layout; "
            "use 'diff_fast' after actions to verify visual changes; use 'diff_accurate' for debugging.",
        )
        scale: float = Field(
            default=1.0,
            description="Device scale factor for screenshot resolution (only for 'screenshot' mode). "
            "1.0 = standard (1280x720, ~850 tokens), 2.0 = Retina/HiDPI (2560x1440, ~3400 tokens). "
            "Use 2.0 only when fine visual details (small text, icons) need verification.",
        )
        baseline: str = Field(
            default="",
            description="Base64-encoded baseline screenshot (required for 'diff_fast' and 'diff_accurate' modes). "
            "Obtain from a prior browser_extract(mode='screenshot') call.",
        )
        similarity_threshold: float = Field(
            default=0.9,
            description="Similarity threshold for 'diff_fast' mode (0.0-1.0). "
            "Values below this indicate significant change. Default: 0.9 (90% similar).",
        )
        color_tolerance: float = Field(
            default=0.1,
            description="Color tolerance for 'diff_accurate' mode (0.0-1.0). "
            "Higher values ignore minor color differences. Default: 0.1.",
        )
        mismatch_threshold: float = Field(
            default=5.0,
            description="Mismatch threshold for 'diff_accurate' mode (0-100%). "
            "Changes above this are considered significant. Default: 5.0 (5%).",
        )
        include_aa: bool = Field(
            default=True,
            description="Enable anti-aliasing detection for 'diff_accurate' mode. "
            "When True, anti-aliased pixels are marked separately (yellow) and not counted. Default: True.",
        )
        resume_cursor: int = Field(
            default=0,
            description="Cursor position to resume reading from (only for 'text' mode). "
            "Use the value suggested by the previous extract_text call's truncation note.",
        )
        max_length: int = Field(
            default=20000,
            description="Maximum number of characters to extract (only for 'text' mode). "
            "Prevents context window overflow on large pages. Default: 20000.",
        )
        selector: str = Field(
            default="",
            description="CSS or XPath selector to precisely target elements (only for 'text' mode). "
            "Use this to strip out noise (like ads, headers) and extract only the relevant content. Example: '.article-content' or 'main'.",
        )
        extraction_schema: str = Field(
            default="",
            description="JSON Schema string defining desired structured output (only for 'text' mode). "
            "When provided, the tool uses an LLM to extract data matching this schema from the page text, "
            "returning validated JSON instead of raw text. This keeps your context window clean. "
            "Example: '{\"type\":\"object\",\"properties\":{\"title\":{\"type\":\"string\"},\"price\":{\"type\":\"string\"}}}'",
        )
        already_collected: str = Field(
            default="",
            description="JSON array of previously collected items to avoid duplicates (only with 'schema'). "
            "When paginating/scrolling through results, pass prior items here so the extractor skips them. "
            "Example: '[{\"title\":\"Item A\",\"price\":\"$10\"}]'",
        )

    @tool("browser_extract_tool", args_schema=ExtractInput)
    async def browser_extract(
        mode: str = "text",
        scale: float = 1.0,
        baseline: str = "",
        similarity_threshold: float = 0.9,
        color_tolerance: float = 0.1,
        mismatch_threshold: float = 5.0,
        include_aa: bool = True,
        resume_cursor: int = 0,
        max_length: int = 20000,
        selector: str = "",
        extraction_schema: str = "",
        already_collected: str = "",
    ) -> str:
        """Extract content from the current page.

        mode='text': returns all visible text — use for reading content, tables, data.
        mode='screenshot': returns base64 JPEG (1280x720, q=50) — use only for visual verification.
        mode='diff_fast': quick visual change detection (~2ms, perceptual hash similarity).
        mode='diff_accurate': detailed visual analysis (~100ms, pixel-level mismatch + diff image).

        When 'schema' is provided with mode='text', returns structured JSON instead of raw text.
        """
        if mode == "screenshot":
            return await session.extract_screenshot(scale=scale)
        if mode == "diff_fast":
            if not baseline:
                return (
                    "Error: 'baseline' parameter is required for diff_fast mode. "
                    "First capture a baseline with browser_extract(mode='screenshot')."
                )
            result = await session.compare_screenshots(
                baseline, strategy="fast", similarity_threshold=similarity_threshold
            )
            return result.to_llm_message()
        if mode == "diff_accurate":
            if not baseline:
                return (
                    "Error: 'baseline' parameter is required for diff_accurate mode. "
                    "First capture a baseline with browser_extract(mode='screenshot')."
                )
            result = await session.compare_screenshots(
                baseline,
                strategy="accurate",
                color_tolerance=color_tolerance,
                mismatch_threshold=mismatch_threshold,
                include_aa=include_aa,
            )
            return result.to_llm_message()

        # Text mode — with optional structured extraction
        if extraction_schema:
            return mark_untrusted(
                await session.extract_structured(
                    schema_json=extraction_schema,
                    selector=selector,
                    already_collected_json=already_collected,
                )
            )

        return mark_untrusted(
            await session.extract_text(resume_cursor=resume_cursor, max_length=max_length, selector=selector)
        )

    return browser_extract
