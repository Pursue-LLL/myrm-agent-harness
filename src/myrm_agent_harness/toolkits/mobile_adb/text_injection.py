"""UTF-8 text injection primitives for Android ADB.

[INPUT]
- run_shell: async callable executing an adb shell command, text: str

[OUTPUT]
- inject_text_utf8 -> (success, detail) — injects multilingual text into the focused field

[POS]
Solves the native ASCII-only limitation of ``adb shell input text``: CJK, emoji and
whitespace-bearing strings are routed through a clipboard broadcast with a percent-escaped
fallback, so mobile agents can type into real apps without losing characters.
"""

from __future__ import annotations

import base64
import logging
from collections.abc import Awaitable, Callable

logger = logging.getLogger(__name__)

ShellRunner = Callable[[str], Awaitable[tuple[int, str, str]]]

_ASCII_FAST_PATH_EXCLUDED = (" ", "\n", "'", '"')


async def inject_text_utf8(run_shell: ShellRunner, text: str) -> tuple[bool, str]:
    """Inject UTF-8 text (CJK, emoji, whitespace) into the currently focused field.

    Strategy:
    1. Pure ASCII without whitespace/quotes → fast native ``input text``.
    2. Otherwise → base64-decoded clipboard broadcast, then percent-escaped ``input text``.
    """
    if not text:
        return True, "Empty text provided."

    if text.isascii() and not any(ch in text for ch in _ASCII_FAST_PATH_EXCLUDED):
        code, out, err = await run_shell(f"input text {text}")
        return code == 0, (out + " " + err).strip()

    encoded = base64.b64encode(text.encode("utf-8")).decode("ascii")
    inject_script = (
        f"text=$(echo '{encoded}' | base64 -d); "
        f'am broadcast -a clipper.set -e text "$text" >/dev/null 2>&1 || '
        f"input text \"$(echo '{encoded}' | base64 -d | sed 's/ /%s/g')\""
    )
    code, out, err = await run_shell(inject_script)
    if code == 0:
        return True, "Text injected successfully."

    logger.warning("UTF-8 clipboard injection failed; falling back to escaped input.")
    fallback = text.replace(" ", "%s")
    code, out, err = await run_shell(f"input text {fallback}")
    return code == 0, (out + " " + err).strip()
