"""Content extraction and screenshot comparison APIs for BrowserSession.

[INPUT]
- session.extractor::Extractor (POS: content extraction manager)
- session.structured_extractor::StructuredExtractor (POS: LLM-based structured data extraction)

[OUTPUT]
- BrowserSessionExtractionMixin: extract_text, extract_structured, extract_media, screenshot compare/export helpers

[POS]
BrowserSession aggregate-root mixin. Owns DOM/vision extraction, pagination, vault offload, and screenshot diff helpers.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Literal, Protocol, runtime_checkable

from myrm_agent_harness.toolkits.browser.diff import ComparisonResult

if TYPE_CHECKING:
    from .extractor import Extractor

logger = logging.getLogger(__name__)


@runtime_checkable
class ContentVault(Protocol):
    """Minimal vault interface for persisting large extracted content."""

    def put(self, content: str | bytes, filename: str, content_type: str | None = None, description: str = "") -> str:
        """Store content and return a URI pointer (e.g. ``vault://<uuid>``)."""
        ...


class BrowserSessionExtractionMixin:
    """extract_text, structured extraction, media URLs, screenshots, and PDF export."""

    async def extract_text(self, resume_cursor: int = 0, max_length: int = 20000, selector: str = "") -> str:
        """Extract page text with automatic vision fallback for Canvas/SVG-heavy pages."""
        await self._ensure_components()
        extractor = self._require_extractor()
        tab_id = self._tab_controller.get_active_tab_id()

        import hashlib

        current_hash = hashlib.md5(f"{selector}".encode()).hexdigest()

        snapshot_data = self._tab_controller.get_text_snapshot(tab_id)
        if resume_cursor > 0 and snapshot_data is not None and snapshot_data[1] == current_hash:
            full_text = snapshot_data[0]
        else:
            full_text = await extractor.extract_full_text(selector=selector)

            if len(full_text.strip()) < 50 and resume_cursor == 0 and self._vision_llm is not None:
                has_visual = await extractor.detect_significant_visual_content()
                if has_visual:
                    vision_text = await self._vision_extract_text(extractor)
                    if vision_text:
                        full_text = vision_text

            self._tab_controller.set_text_snapshot(tab_id, full_text, current_hash)

        chunk = full_text[resume_cursor : resume_cursor + max_length]
        total_len = len(full_text)

        if resume_cursor + max_length < total_len:
            next_cursor = resume_cursor + max_length
            if total_len > 100000 and resume_cursor == 0 and self._content_vault is not None:
                try:
                    page = self._tab_controller.get_active_page()
                    url = page.url
                    vault_uri = self._content_vault.put(
                        content=full_text,
                        filename="Extracted_Web_Content.md",
                        description=f"Extracted from {url} with selector '{selector}'",
                    )
                    logger.warning("BrowserSession: Extracted content extremely long, saved to vault: %s", vault_uri)
                    return f"[System Note: WebpageContent极长 ({total_len} Characters)， is 了节省您  Context Window， already 整体固化至沙箱工件库。]\n\n工件Link: {vault_uri}\n\n or less 是前 {max_length} Characters预览：\n{chunk}"
                except Exception as e:
                    logger.warning("Failed to save to Vault: %s", e)

            chunk += f"\n\n[System Note: Text is extremely long and truncated at {next_cursor} chars. {total_len - next_cursor} chars remaining. Please call extract_text again with resume_cursor={next_cursor} to get the next page.]"

        return chunk

    async def extract_structured(
        self,
        schema_json: str,
        selector: str = "",
        already_collected_json: str = "",
    ) -> str:
        """Extract structured data from page text using LLM + JSON Schema."""
        import json as json_mod

        if not self._structured_extractor.enabled:
            return "[Error] Structured extraction unavailable: no vision_llm configured for this session."

        await self._ensure_components()
        extractor = self._require_extractor()

        try:
            schema = json_mod.loads(schema_json)
        except json_mod.JSONDecodeError as e:
            return f"[Error] Invalid JSON Schema: {e}"

        already_collected: list[dict] | None = None
        if already_collected_json:
            try:
                already_collected = json_mod.loads(already_collected_json)
                if not isinstance(already_collected, list):
                    already_collected = None
            except json_mod.JSONDecodeError:
                pass

        full_text = await extractor.extract_full_text(selector=selector)

        if not full_text.strip():
            if self._vision_llm is not None:
                has_visual = await extractor.detect_significant_visual_content()
                if has_visual:
                    return await self._vision_extract_structured(extractor, schema_json, already_collected)
            return "[Error] No text content found on page (selector may be too restrictive)."

        return await self._structured_extractor.extract(
            text=full_text,
            schema=schema,
            already_collected=already_collected,
        )

    async def _vision_extract_text(self, extractor: Extractor) -> str:
        """Extract page content via Vision LLM when DOM text is insufficient."""
        try:
            screenshot_b64 = await extractor.extract_screenshot()
            from langchain_core.messages import HumanMessage

            message = HumanMessage(
                content=[
                    {
                        "type": "text",
                        "text": (
                            "Extract ALL visible text and data from this page screenshot. "
                            "Include headings, labels, values, chart data, legends, and any readable information. "
                            "Output as structured plain text. Be thorough."
                        ),
                    },
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{screenshot_b64}"}},
                ]
            )
            response = await self._vision_llm.ainvoke([message])  # type: ignore[union-attr]
            content = str(response.content).strip()
            if content:
                logger.info("BrowserSession: Vision fallback extracted %d chars", len(content))
                return f"[Vision Extracted]\n{content}"
        except Exception as e:
            logger.warning("BrowserSession: Vision text fallback failed: %s", e)
        return ""

    async def _vision_extract_structured(
        self,
        extractor: Extractor,
        schema_json: str,
        already_collected: list[dict] | None,
    ) -> str:
        """Extract structured data via Vision LLM when DOM text is empty."""
        import json as json_mod

        try:
            screenshot_b64 = await extractor.extract_screenshot()
            from langchain_core.messages import HumanMessage

            already_note = ""
            if already_collected:
                already_note = f"\n\nAlready collected (skip duplicates):\n{json_mod.dumps(already_collected, ensure_ascii=False)}"

            message = HumanMessage(
                content=[
                    {
                        "type": "text",
                        "text": (
                            f"Extract structured data from this page screenshot according to the JSON Schema below. "
                            f"Output ONLY a valid JSON object/array conforming to the schema. "
                            f"If a field cannot be determined from the image, use null.\n\n"
                            f"JSON Schema:\n{schema_json}{already_note}"
                        ),
                    },
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{screenshot_b64}"}},
                ]
            )
            response = await self._vision_llm.ainvoke([message])  # type: ignore[union-attr]
            content = str(response.content).strip()

            if content.startswith("```"):
                lines = content.split("\n")
                content = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

            json_mod.loads(content)
            logger.info("BrowserSession: Vision structured extraction succeeded")
            return content
        except json_mod.JSONDecodeError:
            return content if content else "[Error] Vision extraction returned invalid JSON."
        except Exception as e:
            logger.warning("BrowserSession: Vision structured fallback failed: %s", e)
            return f"[Error] Vision structured extraction failed: {e}"

    async def extract_screenshot(self, scale: float = 1.0) -> str:
        """ExtractScreenshot(Base64 JPEG)"""
        await self._ensure_components()
        extractor = self._require_extractor()

        retina = scale >= 2.0
        return await extractor.extract_screenshot(retina)

    async def extract_media(
        self,
        selector: str = "",
        max_images: int = 50,
        max_videos: int = 20,
        max_audios: int = 10,
    ) -> str:
        """Extract all high-value media resource URLs from the page."""
        await self._ensure_components()
        extractor = self._require_extractor()
        return await extractor.extract_media(
            selector=selector,
            max_images=max_images,
            max_videos=max_videos,
            max_audios=max_audios,
        )

    async def compare_screenshots(
        self,
        baseline: str,
        strategy: Literal["fast", "accurate", "auto"] = "auto",
        similarity_threshold: float = 0.9,
        color_tolerance: float = 0.1,
        mismatch_threshold: float = 5.0,
        include_aa: bool = True,
    ) -> ComparisonResult:
        """对比CurrentScreenshot and 基准Screenshot"""
        await self._ensure_components()
        extractor = self._require_extractor()
        return await extractor.compare_screenshots(
            baseline,
            strategy,
            similarity_threshold=similarity_threshold,
            color_tolerance=color_tolerance,
            mismatch_threshold=mismatch_threshold,
            include_aa=include_aa,
        )

    async def compare_screenshot(self) -> str:
        """对比Current and 上次Screenshot"""
        await self._ensure_components()
        extractor = self._require_extractor()

        return await extractor.compare_screenshot()

    async def export_pdf(self, path: str) -> str:
        """Export PDF  to 指定Path"""
        await self._ensure_components()
        extractor = self._require_extractor()

        return await extractor.export_pdf(path)
