"""Cross-platform Chromium data directory locator.


[INPUT]
- types::ChromiumBrowser (POS: discovered Chromium browser info)

[OUTPUT]
- discover_browsers: discover locally installed Chromium-based browsers

[POS]
Cross-platform Chromium data directory detector. Supports Chrome and Edge (both Chromium-based,
identical data format). Auto-detects platform-specific paths for macOS/Linux/Windows.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from .types import ChromiumBrowser

logger = logging.getLogger(__name__)

_BROWSER_PATHS: dict[str, dict[str, str]] = {
    "darwin": {
        "Chrome": "Library/Application Support/Google/Chrome",
        "Edge": "Library/Application Support/Microsoft Edge",
    },
    "linux": {
        "Chrome": ".config/google-chrome",
        "Edge": ".config/microsoft-edge",
    },
    "win32": {
        "Chrome": r"Google\Chrome\User Data",
        "Edge": r"Microsoft\Edge\User Data",
    },
}


def discover_browsers() -> list[ChromiumBrowser]:
    """Discover locally installed Chromium-based browsers.

    Returns:
        List of discovered browsers with their data directories.
        Empty list if no supported browsers are found.
    """
    platform = sys.platform
    paths = _BROWSER_PATHS.get(platform)
    if not paths:
        logger.warning("Unsupported platform for browser data: %s", platform)
        return []

    home = Path.home()
    results: list[ChromiumBrowser] = []

    for name, rel_path in paths.items():
        if platform == "win32":
            local_appdata = os.environ.get("LOCALAPPDATA", "")
            if not local_appdata:
                continue
            data_dir = Path(local_appdata) / rel_path
        else:
            data_dir = home / rel_path

        if data_dir.is_dir():
            results.append(ChromiumBrowser(name=name, data_dir=str(data_dir)))
            logger.info("Discovered %s at %s", name, data_dir)

    return results
