"""Content extraction — single responsibility.


[INPUT]
- patchright.async_api::Page (POS: Patchright page instance)
- diff::FastComparator (POS: fast screenshot comparison)
- diff::AccurateComparator (POS: accurate screenshot comparison)
- diff::FastComparisonResult (POS: fast comparison result)
- diff::AccurateComparisonResult (POS: accurate comparison result)

[OUTPUT]
- Extractor: content extraction manager

[POS]
Content extraction manager. Responsibilities:
1. Text extraction (DOM→Markdown with SVG text/tspan support)
2. Screenshot capture (JPEG compression)
3. Screenshot comparison (fast dHash / accurate Canvas API)
4. PDF export
5. Visual content detection (Canvas/SVG significance check for vision fallback)
6. Media extraction (images/videos/audio direct URLs with intelligent filtering)

Single responsibility: only handles content extraction logic; does not handle navigation, snapshot, interaction, etc.
"""

from __future__ import annotations

import base64
import logging
from typing import TYPE_CHECKING, Literal

from myrm_agent_harness.toolkits.browser.diff import (
    AccurateComparisonResult,
    FastComparisonResult,
)
from myrm_agent_harness.toolkits.browser.diff.screenshot_comparator import (
    ScreenshotComparator,
)
from myrm_agent_harness.toolkits.browser.utils.selectors import PASSWORD_FIELD_SELECTOR

if TYPE_CHECKING:
    from patchright.async_api import Page

logger = logging.getLogger(__name__)

_SCREENSHOT_QUALITY = 50
_SCREENSHOT_MAX_WIDTH = 1280
_SCREENSHOT_MAX_HEIGHT = 720


class Extractor:
    """ContentExtract管理器 — 单一职责

    职责:
    1. textExtract
    2. ScreenshotExtract(JPEG Compress)
    3. PDF 导出

     not 涉 and :导航、SnapshotGenerate、Element交互、Screenshot对比 etc.。
    """

    def __init__(self, page: Page):
        """Initialize Extractor

        Args:
            page: Patchright Page Instance
        """
        self._page = page
        self._prev_screenshot: str | None = None
        self._comparator = ScreenshotComparator(page.context)

    async def extract_full_text(self, selector: str = "") -> str:
        """ExtractPage全量text(Support Iframe 穿透 and  Markdown 语义Convert)。"""
        js_script = f"""
            (selector) => {{
                const PASSWORD_SELECTOR = `{PASSWORD_FIELD_SELECTOR}`;

                function isHidden(node) {{
                    if (node.nodeType !== Node.ELEMENT_NODE) return false;
                    const style = window.getComputedStyle(node);
                    return style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0';
                }}

                function nodeToMarkdown(node) {{
                    if (node.nodeType === Node.TEXT_NODE) {{
                        return node.textContent.replace(/\\s+/g, ' ');
                    }}
                    if (node.nodeType !== Node.ELEMENT_NODE) return "";
                    if (isHidden(node)) return "";

                    const tag = node.tagName.toUpperCase();
                    if (['SCRIPT', 'STYLE', 'NOSCRIPT', 'CANVAS'].includes(tag)) {{
                        return "";
                    }}
                    if (tag === 'SVG') {{
                        let svgText = "";
                        node.querySelectorAll('text, tspan').forEach(el => {{
                            const t = el.textContent.trim();
                            if (t) svgText += t + " ";
                        }});
                        return svgText ? "[SVG: " + svgText.trim() + "] " : "";
                    }}

                    if (node.matches(PASSWORD_SELECTOR)) {{
                        return " [PASSWORD HIDDEN] ";
                    }}

                    let md = "";
                    let prefix = "";
                    let suffix = "";

                    if (tag === 'H1') prefix = "\\n# ";
                    else if (tag === 'H2') prefix = "\\n## ";
                    else if (tag === 'H3') prefix = "\\n### ";
                    else if (tag === 'H4') prefix = "\\n#### ";
                    else if (tag === 'H5') prefix = "\\n##### ";
                    else if (tag === 'H6') prefix = "\\n###### ";
                    else if (tag === 'LI') prefix = "\\n- ";
                    else if (tag === 'P' || tag === 'DIV' || tag === 'ARTICLE' || tag === 'SECTION') prefix = "\\n";
                    else if (tag === 'TR') prefix = "| ";

                    md += prefix;
                    if (node.shadowRoot) {{
                        for (let child of node.shadowRoot.childNodes) {{
                            md += nodeToMarkdown(child);
                        }}
                    }}
                    for (let child of node.childNodes) {{
                        md += nodeToMarkdown(child);
                    }}

                    if (tag === 'TD' || tag === 'TH') md += " | ";
                    if (tag === 'A' && node.href && node.href.startsWith('http')) {{
                        md += ` [Link: ${{node.href}}] `;
                    }}
                    if (tag === 'TR') md += "\\n";
                    if (tag === 'TABLE') md += "\\n";

                    return md + suffix;
                }}

                let targetElements = [];
                if (selector) {{
                    try {{
                        targetElements = Array.from(document.querySelectorAll(selector));
                    }} catch (e) {{
                        targetElements = [document.body];
                    }}
                }} else {{
                    targetElements = [document.body];
                }}

                let result = "";
                targetElements.forEach(el => {{
                    if (el) result += nodeToMarkdown(el);
                }});
                return result.trim();
            }}
        """

        full_text = ""
        for i, frame in enumerate(self._page.frames):
            try:
                frame_text = await frame.evaluate(js_script, selector)
                if frame_text and len(frame_text.strip()) > 0:
                    if i > 0:
                        full_text += f"\\n\\n--- Frame {i} Content ---\\n"
                    full_text += frame_text
            except Exception as exc:
                logger.debug("Extractor: could not extract text from frame %d: %s", i, exc)

        import re

        full_text = re.sub(r"\\n{3,}", "\\n\\n", full_text).strip()

        logger.info("Extractor: extracted full markdown length: %d", len(full_text))
        return full_text

    async def extract_screenshot(self, retina: bool = False) -> str:
        """ExtractPageScreenshot(base64 Encoding  JPEG)

        Args:
            retina: Whether using  2x DPR(Retina 高清)

        Returns:
            Base64 Encoding  JPEG Image
        """
        if retina:
            await self._set_device_scale_factor(2.0)

        # Redact password fields in screenshot to prevent privacy leaks
        password_locator = self._page.locator(PASSWORD_FIELD_SELECTOR)

        screenshot_bytes = await self._page.screenshot(
            type="jpeg",
            quality=_SCREENSHOT_QUALITY,
            full_page=False,
            mask=[password_locator],
        )

        if retina:
            await self._set_device_scale_factor(1.0)

        screenshot_base64 = base64.b64encode(screenshot_bytes).decode("utf-8")
        self._prev_screenshot = screenshot_base64

        logger.info("Extractor: captured screenshot (%d bytes)", len(screenshot_base64))
        return screenshot_base64

    async def compare_screenshots(
        self,
        baseline: str,
        strategy: Literal["fast", "accurate", "auto"] = "auto",
        similarity_threshold: float = 0.9,
        color_tolerance: float = 0.1,
        mismatch_threshold: float = 5.0,
        include_aa: bool = True,
    ) -> FastComparisonResult | AccurateComparisonResult:
        """对比CurrentScreenshot and 基准Screenshot

        Args:
            baseline: Base64 Encoding 基准Screenshot
            strategy: 对比Strategy
                - 'auto': Auto选择( based on ImageSize,<800x600 用 accurate,Otherwise用 fast)
                - 'fast': dHash fast检测(~2ms),Return相似度
                - 'accurate': Canvas API 像素级对比(~100ms),Return diff 图
            similarity_threshold: Fast Strategy 相似度阈Value (0.0-1.0, Default 0.9)
            color_tolerance: Accurate Strategy 颜色容忍度 (0.0-1.0, Default 0.1)
            mismatch_threshold: Accurate Strategy  not Match阈Value (0-100, Default 5.0)
            include_aa: Accurate StrategyWhether启用抗锯齿检测 (Default True)

        Returns:
            FastComparisonResult: strategy='fast'  or  auto 选择 fast 时
            AccurateComparisonResult: strategy='accurate'  or  auto 选择 accurate 时

        Raises:
            ValueError: If strategy  not 是 'fast', 'accurate',  or  'auto'
        """
        current = await self.extract_screenshot()

        return await self._comparator.compare(
            baseline=baseline,
            current=current,
            strategy=strategy,
            similarity_threshold=similarity_threshold,
            color_tolerance=color_tolerance,
            mismatch_threshold=mismatch_threshold,
            include_aa=include_aa,
        )

    async def compare_screenshot(self) -> str:
        """对比CurrentScreenshot and 上次Screenshot(便捷Method)

        Returns:
            对比Result textDescription

        Raises:
            RuntimeError: If没 has 上次Screenshot
        """
        if self._prev_screenshot is None:
            raise RuntimeError("No previous screenshot to compare with. Call extract_screenshot first.")

        result = await self.compare_screenshots(self._prev_screenshot, strategy="fast")
        return result.to_llm_message()

    async def export_pdf(self, path: str) -> str:
        """导出Page is  PDF

        Args:
            path: PDF FilePath

        Returns:
            Success消息
        """
        await self._page.pdf(path=path)
        logger.info("Extractor: exported PDF to %s", path)
        return f"Exported PDF to {path}"

    async def detect_significant_visual_content(self) -> bool:
        """Detect if the page contains significant visual content (large Canvas/SVG/img).

        Returns True if visual elements with meaningful dimensions exist,
        indicating the page likely renders content visually rather than via DOM text.
        """
        js = """
            () => {
                const canvases = document.querySelectorAll('canvas');
                for (const c of canvases) {
                    if (c.width > 200 && c.height > 100) return true;
                    const rect = c.getBoundingClientRect();
                    if (rect.width > 200 && rect.height > 100) return true;
                }
                const svgs = document.querySelectorAll('svg');
                for (const s of svgs) {
                    const rect = s.getBoundingClientRect();
                    if (rect.width > 200 && rect.height > 100) return true;
                }
                return false;
            }
        """
        try:
            return await self._page.evaluate(js)
        except Exception:
            return False

    async def extract_media(self, selector: str = "", max_images: int = 50, max_videos: int = 20, max_audios: int = 10) -> str:
        """Extract all high-value media resource URLs from the page.

        Collects images (including lazy-loaded), videos, audio, and OG/Twitter meta
        images. Filters out icons, logos, and tiny decorative elements.

        Args:
            selector: CSS selector to scope extraction (empty = full page)
            max_images: Maximum number of images to return
            max_videos: Maximum number of videos to return
            max_audios: Maximum number of audio items to return
        """
        js_script = f"""
            (params) => {{
                const maxImages = params.maxImages;
                const maxVideos = params.maxVideos;
                const maxAudios = params.maxAudios;
                const selector = params.selector;

                const root = selector
                    ? (document.querySelector(selector) || document.body)
                    : document.body;

                const seen = new Set();
                function abs(url) {{
                    if (!url || url.startsWith('data:') || url.startsWith('blob:')) return null;
                    try {{ return new URL(url, document.baseURI).href; }}
                    catch {{ return null; }}
                }}
                function dedup(url) {{
                    if (!url || seen.has(url)) return null;
                    seen.add(url);
                    return url;
                }}

                const ICON_PATTERNS = /icon|logo|favicon|sprite|avatar|badge|arrow|caret|chevron|spinner/i;
                function isDecorativeImg(el) {{
                    const src = el.getAttribute('src') || '';
                    const cls = el.className || '';
                    const id = el.id || '';
                    if (ICON_PATTERNS.test(src) || ICON_PATTERNS.test(cls) || ICON_PATTERNS.test(id)) return true;
                    const w = el.naturalWidth || el.width || parseInt(el.getAttribute('width')) || 0;
                    const h = el.naturalHeight || el.height || parseInt(el.getAttribute('height')) || 0;
                    if (w > 0 && h > 0 && w < 50 && h < 50) return true;
                    const rect = el.getBoundingClientRect();
                    if (rect.width > 0 && rect.height > 0 && rect.width < 50 && rect.height < 50) return true;
                    return false;
                }}

                function parseSrcset(srcset) {{
                    if (!srcset) return null;
                    const candidates = srcset.split(',').map(s => s.trim().split(/\\s+/));
                    let best = null;
                    let bestW = 0;
                    for (const [url, descriptor] of candidates) {{
                        const w = parseInt(descriptor) || 0;
                        if (w > bestW || !best) {{ best = url; bestW = w; }}
                    }}
                    return abs(best);
                }}

                // Collect images
                const images = [];
                for (const img of root.querySelectorAll('img')) {{
                    if (isDecorativeImg(img)) continue;
                    const src = abs(img.getAttribute('src'))
                        || abs(img.getAttribute('data-src'))
                        || abs(img.getAttribute('data-lazy-src'))
                        || abs(img.getAttribute('data-original'))
                        || parseSrcset(img.getAttribute('srcset'));
                    const url = dedup(src);
                    if (!url) continue;
                    const w = img.naturalWidth || img.width || parseInt(img.getAttribute('width')) || null;
                    const h = img.naturalHeight || img.height || parseInt(img.getAttribute('height')) || null;
                    const alt = (img.getAttribute('alt') || '').slice(0, 80);
                    images.push({{ url, w, h, alt }});
                    if (images.length >= maxImages) break;
                }}

                // <picture><source> elements
                if (images.length < maxImages) {{
                    for (const pic of root.querySelectorAll('picture')) {{
                        for (const source of pic.querySelectorAll('source')) {{
                            const url = dedup(parseSrcset(source.getAttribute('srcset')) || abs(source.getAttribute('src')));
                            if (!url) continue;
                            images.push({{ url, w: null, h: null, alt: '' }});
                            if (images.length >= maxImages) break;
                        }}
                        if (images.length >= maxImages) break;
                    }}
                }}

                // Collect videos
                const videos = [];
                for (const vid of root.querySelectorAll('video')) {{
                    const src = abs(vid.getAttribute('src'));
                    const poster = abs(vid.getAttribute('poster'));
                    if (src) {{
                        const url = dedup(src);
                        if (url) videos.push({{ url, poster: poster || null }});
                    }}
                    for (const source of vid.querySelectorAll('source')) {{
                        const url = dedup(abs(source.getAttribute('src')));
                        if (url) videos.push({{ url, poster: poster || null }});
                    }}
                    if (videos.length >= maxVideos) break;
                }}
                // iframe embeds (YouTube, Vimeo, etc.)
                if (videos.length < maxVideos) {{
                    for (const iframe of root.querySelectorAll('iframe[src]')) {{
                        const src = iframe.getAttribute('src') || '';
                        if (/youtube|vimeo|dailymotion|wistia/.test(src)) {{
                            const url = dedup(abs(src));
                            if (url) videos.push({{ url, poster: null }});
                            if (videos.length >= maxVideos) break;
                        }}
                    }}
                }}

                // Collect audio
                const audios = [];
                for (const aud of root.querySelectorAll('audio')) {{
                    const src = abs(aud.getAttribute('src'));
                    if (src) {{
                        const url = dedup(src);
                        if (url) audios.push({{ url }});
                    }}
                    for (const source of aud.querySelectorAll('source')) {{
                        const url = dedup(abs(source.getAttribute('src')));
                        if (url) audios.push({{ url }});
                    }}
                    if (audios.length >= maxAudios) break;
                }}

                // Meta images (OG, Twitter)
                const metaImages = [];
                for (const meta of document.querySelectorAll('meta[property="og:image"], meta[name="twitter:image"], meta[property="og:image:url"]')) {{
                    const url = dedup(abs(meta.getAttribute('content')));
                    if (url) metaImages.push({{ property: meta.getAttribute('property') || meta.getAttribute('name'), url }});
                }}

                return {{ images, videos, audios, metaImages }};
            }}
        """

        all_media: dict = {"images": [], "videos": [], "audios": [], "metaImages": []}

        for i, frame in enumerate(self._page.frames):
            try:
                frame_media = await frame.evaluate(
                    js_script,
                    {"maxImages": max_images, "maxVideos": max_videos, "maxAudios": max_audios, "selector": selector},
                )
                for key in all_media:
                    all_media[key].extend(frame_media.get(key, []))
            except Exception as exc:
                logger.debug("Extractor: could not extract media from frame %d: %s", i, exc)

        lines: list[str] = []

        imgs = all_media["images"][:max_images]
        if imgs:
            lines.append(f"## Images ({len(imgs)} found)")
            for idx, img in enumerate(imgs, 1):
                parts = [img["url"]]
                dims = []
                if img.get("w") and img.get("h"):
                    dims.append(f"{img['w']}x{img['h']}")
                if img.get("alt"):
                    dims.append(f'alt="{img["alt"]}"')
                if dims:
                    parts.append(f"[{', '.join(dims)}]")
                lines.append(f"{idx}. {' '.join(parts)}")

        vids = all_media["videos"][:max_videos]
        if vids:
            lines.append(f"\n## Videos ({len(vids)} found)")
            for idx, vid in enumerate(vids, 1):
                extra = f" [poster: {vid['poster']}]" if vid.get("poster") else ""
                lines.append(f"{idx}. {vid['url']}{extra}")

        auds = all_media["audios"][:max_audios]
        if auds:
            lines.append(f"\n## Audio ({len(auds)} found)")
            for idx, aud in enumerate(auds, 1):
                lines.append(f"{idx}. {aud['url']}")

        metas = all_media["metaImages"]
        if metas:
            lines.append("\n## Meta Images")
            for m in metas:
                lines.append(f"- {m['property']}: {m['url']}")

        if not lines:
            return "No media resources found on this page."

        result = "\n".join(lines)
        if len(result) > 8000:
            result = result[:7950] + "\n\n... (truncated, use selector to narrow scope)"

        logger.info("Extractor: extracted media — %d images, %d videos, %d audio", len(imgs), len(vids), len(auds))
        return result

    async def _set_device_scale_factor(self, scale: float) -> None:
        """Set设备缩放因子(CDP)

        Args:
            scale: 缩放因子(1.0=normal,2.0=Retina)
        """
        try:
            cdp = await self._page.context.new_cdp_session(self._page)
            await cdp.send(
                "Emulation.setDeviceMetricsOverride",
                {
                    "width": _SCREENSHOT_MAX_WIDTH,
                    "height": _SCREENSHOT_MAX_HEIGHT,
                    "deviceScaleFactor": scale,
                    "mobile": False,
                },
            )
            await cdp.detach()
        except Exception as exc:
            logger.warning(f"Extractor: failed to set DPR: {exc}")
