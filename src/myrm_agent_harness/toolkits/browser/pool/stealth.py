"""Stealth anti-detection script loader.

Loads stealth.js once at module import and caches the content.
The JS script patches browser globals to hide automation fingerprints
(navigator.webdriver, plugins, toString disguise, anti-debugger, etc.).

Injected via BrowserContext.add_init_script() for STEALTH contexts only.

[INPUT]
- (none)

[OUTPUT]
- get_stealth_script: Return the stealth JS script content (cached after first ...

[POS]
Stealth anti-detection script loader.
"""

from __future__ import annotations

from pathlib import Path

_STEALTH_JS_PATH = Path(__file__).parent / "stealth.js"
_stealth_script_cache: str | None = None


def get_stealth_script() -> str:
    """Return the stealth JS script content (cached after first read)."""
    global _stealth_script_cache
    if _stealth_script_cache is None:
        _stealth_script_cache = _STEALTH_JS_PATH.read_text(encoding="utf-8")
    return _stealth_script_cache
