"""UTF-8 & Multilingual Text Input Primitives for Android ADB.

[INPUT]
- client: AndroidAdbClient, text: str

[OUTPUT]
- inject_text_utf8(client, text) -> tuple[bool, str]

[POS]
Solves the native ASCII-only limitation of 'adb shell input text'.
"""

from __future__ import annotations

import base64
import logging

from .client import AndroidAdbClient

logger = logging.getLogger(__name__)


async def inject_text_utf8(client: AndroidAdbClient, text: str) -> tuple[bool, str]:
    """Inject UTF-8 text (including Chinese, Emoji, special chars) into focused field.

    Strategy:
    1. For pure ASCII alphanumeric without whitespace/specials, use fast `input text`.
    2. For UTF-8 / multi-byte / space-containing strings, use ADB broadcast / base64 or clipboard set.
    """
    if not text:
        return True, "Empty text provided."

    # Fast path: pure ASCII non-space strings
    if text.isascii() and " " not in text and "\n" not in text and "'" not in text and '"' not in text:
        code, out, err = await client.run_adb("shell", "input", "text", text)
        return code == 0, (out + " " + err).strip()

    # UTF-8 & special text injection via Base64 clipboard or broadcast helper
    # 1. Set text into Android clipboard via command or broadcast
    b64_str = base64.b64encode(text.encode("utf-8")).decode("ascii")

    # Try setting text directly via ADB broadcast or keyboard helper
    # Fallback to escaped keyevent & base64 decode injection
    inject_script = (
        f"text=$(echo '{b64_str}' | base64 -d); "
        f"am broadcast -a clipper.set -e text \"$text\" >/dev/null 2>&1 || "
        f"input text \"$(echo '{b64_str}' | base64 -d | sed 's/ /%s/g')\""
    )

    code, out, err = await client.run_adb("shell", inject_script)
    if code == 0:
        return True, "Text injected successfully."

    # Final fallback: character-by-character key events for ASCII spaces/returns
    fallback_text = text.replace(" ", "%s")
    code, out, err = await client.run_adb("shell", "input", "text", fallback_text)
    return code == 0, (out + " " + err).strip()
