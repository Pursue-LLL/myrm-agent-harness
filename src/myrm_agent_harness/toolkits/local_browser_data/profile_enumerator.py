"""Enumerate Chromium browser profiles.


[INPUT]
- types::ChromiumBrowser (POS: discovered Chromium browser info)
- types::BrowserProfile (POS: browser profile info)

[OUTPUT]
- enumerate_profiles: enumerate all browser profiles

[POS]
Chromium multi-profile enumerator. Parses Local State JSON to discover all user profiles,
supports Chrome and Edge multi-profile configurations. Falls back to Default when Local State is unreadable.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from .types import BrowserProfile, ChromiumBrowser

logger = logging.getLogger(__name__)


def enumerate_profiles(browser: ChromiumBrowser) -> list[BrowserProfile]:
    """Enumerate all profiles for a Chromium browser.

    Parses the ``Local State`` JSON file under the browser data directory
    to discover profile directories and display names.

    Args:
        browser: Discovered browser with data directory path.

    Returns:
        List of profiles. Falls back to a single "Default" profile
        when ``Local State`` is unreadable.
    """
    data_dir = Path(browser.data_dir)
    local_state_path = data_dir / "Local State"

    if local_state_path.is_file():
        try:
            raw = local_state_path.read_text(encoding="utf-8")
            state = json.loads(raw)
            info_cache: dict[str, dict[str, str]] = state.get("profile", {}).get("info_cache") or {}
            if info_cache:
                profiles = [
                    BrowserProfile(
                        directory=dir_name,
                        display_name=info.get("name", dir_name),
                        browser_name=browser.name,
                    )
                    for dir_name, info in info_cache.items()
                ]
                logger.info(
                    "Found %d profiles for %s",
                    len(profiles),
                    browser.name,
                )
                return profiles
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning(
                "Failed to parse Local State for %s: %s",
                browser.name,
                exc,
            )

    return [
        BrowserProfile(
            directory="Default",
            display_name="Default",
            browser_name=browser.name,
        )
    ]
