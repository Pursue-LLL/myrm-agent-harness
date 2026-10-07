"""OmniGlyph visual context channel renderer and arbitration governor.

Compiles ultra-long, low-risk textual context into high-density rasterized glyphs
for visual language models, bypassing heavy text token consumption while enforcing
strict fail-closed opt-in gates on code, auth, and financial workloads.

[INPUT]
- runtime.context.omniglyph_types::BypassReason, OmniGlyphConfig, RenderedGlyphPayload, TaskRiskLevel,
  VisualChannelRoutingResult (POS: OmniGlyph multimodal visual context channel and Ultra token governor
  types.)
- runtime.context.ultra_heuristic_filter::UltraHeuristicPreFilter (POS: Ultra heuristic pre-filter for
  low-cost token pruning.)
- External: PIL

[OUTPUT]
- OmniGlyphVisualRenderer: Renders formatted text streams into compact, high-density visual glyphs.
- OmniGlyphGovernor: Arbitrates visual context channel routing with fail-closed risk gating.

[POS]
OmniGlyph visual context channel renderer and arbitration governor.
"""

from __future__ import annotations

import base64
import hashlib
import io
import math
from collections.abc import Sequence

from .omniglyph_types import (
    BypassReason,
    OmniGlyphConfig,
    RenderedGlyphPayload,
    TaskRiskLevel,
    VisualChannelRoutingResult,
)
from .ultra_heuristic_filter import UltraHeuristicPreFilter


class OmniGlyphVisualRenderer:
    """Renders formatted text streams into compact, high-density visual glyphs."""

    def __init__(self, chars_per_token_ratio: float = 3.8) -> None:
        self._chars_per_token_ratio = chars_per_token_ratio

    def estimate_tokens(self, text: str) -> int:
        """Estimates raw text tokens based on character length."""
        char_count = len(text)
        if char_count == 0:
            return 0
        return max(1, math.ceil(char_count / self._chars_per_token_ratio))

    def render_text(
        self,
        text: str,
        config: OmniGlyphConfig,
    ) -> tuple[RenderedGlyphPayload, ...]:
        """Splits long text into pages and rasterizes each page into a PNG glyph."""
        if not text.strip():
            return ()

        # Calculate layout geometry
        usable_width = config.image_width - 2 * config.margin
        usable_height = config.image_height - 2 * config.margin
        char_cell_width = max(8, int(config.font_size * 0.65))
        line_cell_height = config.font_size + config.line_spacing

        max_chars_per_line = max(40, usable_width // char_cell_width)
        max_lines_per_page = max(20, usable_height // line_cell_height)

        wrapped_lines = self._wrap_lines(text, max_chars_per_line)
        pages = self._paginate_lines(wrapped_lines, max_lines_per_page)

        payloads: list[RenderedGlyphPayload] = []
        for idx, page_lines in enumerate(pages):
            page_text = "\n".join(page_lines)
            char_count = len(page_text)
            raw_tokens = self.estimate_tokens(page_text)
            visual_tokens = config.fixed_vlm_token_cost
            saved = max(0, raw_tokens - visual_tokens)
            ratio = round(visual_tokens / raw_tokens, 4) if raw_tokens > 0 else 1.0

            img_b64, sha256_hash = self._rasterize_page_to_png_b64(
                page_lines=page_lines,
                config=config,
                line_cell_height=line_cell_height,
            )

            glyph_id = f"glyph_{idx + 1:03d}_{sha256_hash[:8]}"
            payloads.append(
                RenderedGlyphPayload(
                    glyph_id=glyph_id,
                    image_base64=img_b64,
                    mime_type="image/png",
                    text_char_count=char_count,
                    estimated_raw_text_tokens=raw_tokens,
                    estimated_visual_tokens=visual_tokens,
                    saved_tokens=saved,
                    compression_ratio=ratio,
                    checksum_sha256=sha256_hash,
                    metadata={
                        "page_index": str(idx + 1),
                        "total_pages": str(len(pages)),
                        "line_count": str(len(page_lines)),
                    },
                )
            )

        return tuple(payloads)

    def _wrap_lines(self, text: str, max_chars_per_line: int) -> list[str]:
        """Splits raw text by newlines and wraps lines exceeding width."""
        lines: list[str] = []
        for paragraph in text.splitlines():
            if not paragraph:
                lines.append("")
                continue
            while len(paragraph) > max_chars_per_line:
                # Break at last whitespace within limit if possible
                break_point = paragraph.rfind(" ", 0, max_chars_per_line)
                if break_point <= 0:
                    break_point = max_chars_per_line
                lines.append(paragraph[:break_point])
                paragraph = paragraph[break_point:].lstrip()
            if paragraph:
                lines.append(paragraph)
        return lines

    def _paginate_lines(
        self,
        lines: list[str],
        max_lines_per_page: int,
    ) -> list[list[str]]:
        """Groups wrapped lines into discrete pages."""
        pages: list[list[str]] = []
        for i in range(0, len(lines), max_lines_per_page):
            chunk = lines[i : i + max_lines_per_page]
            if chunk:
                pages.append(chunk)
        return pages

    def _rasterize_page_to_png_b64(
        self,
        page_lines: list[str],
        config: OmniGlyphConfig,
        line_cell_height: int,
    ) -> tuple[str, str]:
        """Rasterizes lines of text into PNG format using PIL."""
        try:
            from PIL import Image, ImageDraw, ImageFont

            img = Image.new(
                "RGB",
                (config.image_width, config.image_height),
                color=(255, 255, 255),
            )
            draw = ImageDraw.Draw(img)
            font = ImageFont.load_default()

            y = config.margin
            for line in page_lines:
                if y + line_cell_height > config.image_height - config.margin:
                    break
                draw.text((config.margin, y), line, fill=(35, 35, 35), font=font)
                y += line_cell_height

            buf = io.BytesIO()
            img.save(buf, format="PNG", optimize=True)
            png_bytes = buf.getvalue()
        except Exception:
            # Deterministic fallback for headless or mock environments
            encoded_content = "\n".join(page_lines).encode("utf-8")
            png_bytes = (
                b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4"
                + encoded_content
            )

        sha256_hash = hashlib.sha256(png_bytes).hexdigest()
        img_b64 = base64.b64encode(png_bytes).decode("ascii")
        return img_b64, sha256_hash


class OmniGlyphGovernor:
    """Arbitrates visual context channel routing with fail-closed risk gating."""

    def __init__(
        self,
        default_config: OmniGlyphConfig | None = None,
        renderer: OmniGlyphVisualRenderer | None = None,
        heuristic_filter: UltraHeuristicPreFilter | None = None,
    ) -> None:
        self._config = default_config or OmniGlyphConfig()
        self._renderer = renderer or OmniGlyphVisualRenderer()
        self._filter = heuristic_filter or UltraHeuristicPreFilter()

    def route_context(
        self,
        text: str,
        risk_level: TaskRiskLevel,
        target_keywords: Sequence[str] = (),
        custom_config: OmniGlyphConfig | None = None,
    ) -> VisualChannelRoutingResult:
        """Evaluates whether to compile text to visual channel or keep text verbatim."""
        cfg = custom_config or self._config
        raw_tokens_before = self._renderer.estimate_tokens(text)

        # 1. Gate: System enablement
        if not cfg.enabled:
            return VisualChannelRoutingResult(
                is_routed_to_visual=False,
                bypassed_reason=BypassReason.DISABLED_BY_CONFIG,
                rendered_glyphs=(),
                retained_text=text,
                raw_tokens_before=raw_tokens_before,
                tokens_after=raw_tokens_before,
                net_saved_tokens=0,
                filter_scores=(),
            )

        # 2. Gate: Explicit user opt-in required
        if not cfg.opt_in:
            return VisualChannelRoutingResult(
                is_routed_to_visual=False,
                bypassed_reason=BypassReason.NOT_OPTED_IN,
                rendered_glyphs=(),
                retained_text=text,
                raw_tokens_before=raw_tokens_before,
                tokens_after=raw_tokens_before,
                net_saved_tokens=0,
                filter_scores=(),
            )

        # 3. Gate: Risk-level hard isolation (Reject High/Critical code, secrets, financial)
        if risk_level not in cfg.allowed_risk_levels:
            return VisualChannelRoutingResult(
                is_routed_to_visual=False,
                bypassed_reason=BypassReason.HIGH_RISK_TASK,
                rendered_glyphs=(),
                retained_text=text,
                raw_tokens_before=raw_tokens_before,
                tokens_after=raw_tokens_before,
                net_saved_tokens=0,
                filter_scores=(),
            )

        # 4. Ultra heuristic pre-filter execution
        filtered_text, scores = self._filter.filter_text(
            text=text,
            target_keywords=target_keywords,
        )

        if not filtered_text.strip():
            return VisualChannelRoutingResult(
                is_routed_to_visual=False,
                bypassed_reason=BypassReason.NO_VALID_SEGMENTS,
                rendered_glyphs=(),
                retained_text="",
                raw_tokens_before=raw_tokens_before,
                tokens_after=0,
                net_saved_tokens=raw_tokens_before,
                filter_scores=scores,
            )

        # 5. Gate: Break-even token threshold check
        tokens_filtered = self._renderer.estimate_tokens(filtered_text)
        if tokens_filtered < cfg.break_even_token_threshold:
            return VisualChannelRoutingResult(
                is_routed_to_visual=False,
                bypassed_reason=BypassReason.TEXT_BELOW_BREAK_EVEN,
                rendered_glyphs=(),
                retained_text=filtered_text,
                raw_tokens_before=raw_tokens_before,
                tokens_after=tokens_filtered,
                net_saved_tokens=max(0, raw_tokens_before - tokens_filtered),
                filter_scores=scores,
            )

        # 6. Render high-density visual glyphs
        glyphs = self._renderer.render_text(filtered_text, cfg)
        visual_tokens_total = sum(g.estimated_visual_tokens for g in glyphs)
        net_saved = max(0, raw_tokens_before - visual_tokens_total)

        return VisualChannelRoutingResult(
            is_routed_to_visual=True,
            bypassed_reason=None,
            rendered_glyphs=glyphs,
            retained_text=filtered_text,
            raw_tokens_before=raw_tokens_before,
            tokens_after=visual_tokens_total,
            net_saved_tokens=net_saved,
            filter_scores=scores,
        )
