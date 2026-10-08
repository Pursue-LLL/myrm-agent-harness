"""Inbound multimodal content firewall.

Sanitizes external web pages, emails, and rich documents before they enter the
agent's vision. Strips hidden text, invisible styles, zero-width steganography,
and structural markdown prompt hijacking.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import re
import time

from .types import FirewallSanitizedPayload

# Invisible CSS styling patterns commonly used in indirect prompt injection attacks
_INVISIBLE_STYLE_PATTERN = re.compile(
    r"(?i)<[^>]*style\s*=\s*[\"'][^\"']*(?:"
    r"display\s*:\s*none"
    r"|visibility\s*:\s*hidden"
    r"|opacity\s*:\s*0"
    r"|font-size\s*:\s*0(?:px|pt|em)?"
    r"|color\s*:\s*(?:white|#fff(?:fff)?|rgba\(\s*255\s*,\s*255\s*,\s*255\s*,\s*0(?:\.\d+)?\))"
    r")[^\"']*[\"'][^>]*>(.*?)</[^>]+>",
    re.DOTALL,
)

# Zero-width spaces and invisible steganography Unicode characters
_ZERO_WIDTH_CHARS = re.compile(r"[\u200B-\u200D\uFEFF\u2060\u200E\u200F]")

# System message spoofing tags in Markdown or text
_SYSTEM_TAG_INJECTION = re.compile(
    r"(?i)(<\|im_start\|>\s*system|\[SYSTEM\]\s*:|<<SYS>>|Role\s*:\s*System)"
)

# HTML comment embedded injections (e.g., <!-- ignore instructions ... -->)
_HTML_COMMENT_INJECTION = re.compile(
    r"(?i)<!--\s*(?:ignore|disregard|forget|system|developer|admin|payload)[^>]*-->",
    re.DOTALL,
)


class InboundContentFirewall:
    """Sanitizes inbound external multimodal content before entering LLM context."""

    def sanitize(self, raw_content: str, source_type: str = "web_page") -> FirewallSanitizedPayload:
        """Strip invisible styles, zero-width steganography, and malicious injection headers."""
        start_time = time.perf_counter()

        if not raw_content:
            latency = (time.perf_counter() - start_time) * 1000.0
            return FirewallSanitizedPayload(
                source_type=source_type,
                raw_content="",
                sanitized_content="",
                hidden_text_stripped_count=0,
                has_markdown_injection=False,
                stripped_tags=[],
                latency_ms=latency,
            )

        stripped_tags: list[str] = []
        hidden_stripped_count = 0
        working_content = raw_content

        # 1. Strip invisible CSS elements
        for match in _INVISIBLE_STYLE_PATTERN.finditer(working_content):
            hidden_stripped_count += len(match.group(0))
            stripped_tags.append("invisible_style_tag")
        working_content = _INVISIBLE_STYLE_PATTERN.sub("", working_content)

        # 2. Strip HTML comment injections
        for match in _HTML_COMMENT_INJECTION.finditer(working_content):
            hidden_stripped_count += len(match.group(0))
            stripped_tags.append("html_comment_injection")
        working_content = _HTML_COMMENT_INJECTION.sub("", working_content)

        # 3. Strip zero-width characters
        zw_matches = _ZERO_WIDTH_CHARS.findall(working_content)
        if zw_matches:
            hidden_stripped_count += len(zw_matches)
            stripped_tags.append("zero_width_chars")
            working_content = _ZERO_WIDTH_CHARS.sub("", working_content)

        # 4. Detect and defang system header injections
        has_md_injection = bool(_SYSTEM_TAG_INJECTION.search(working_content))
        if has_md_injection:
            stripped_tags.append("system_tag_injection")
            working_content = _SYSTEM_TAG_INJECTION.sub("[REDACTED_SYSTEM_TAG]", working_content)

        latency = (time.perf_counter() - start_time) * 1000.0

        return FirewallSanitizedPayload(
            source_type=source_type,
            raw_content=raw_content,
            sanitized_content=working_content,
            hidden_text_stripped_count=hidden_stripped_count,
            has_markdown_injection=has_md_injection,
            stripped_tags=stripped_tags,
            latency_ms=latency,
        )
