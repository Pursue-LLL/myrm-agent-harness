"""Unified locale normalization for harness modules.

[INPUT]
- (none — leaf module)

[OUTPUT]
- LocaleResolver: BCP-47 normalization and Chinese detection

[POS]
Shared locale utilities consumed by channel i18n, error diagnostics, and
component text fallbacks. Single source of truth for locale string handling.
"""

from __future__ import annotations

import os
from typing import Final

DEFAULT_LOCALE: Final[str] = "en"
SUPPORTED_CATALOG_LOCALES: Final[frozenset[str]] = frozenset({"en", "zh-CN"})

# Chinese-first IM platforms when no user preference is available.
PLATFORM_DEFAULT_LOCALES: Final[dict[str, str]] = {
    "feishu": "zh-CN",
    "dingtalk": "zh-CN",
    "wechat": "zh-CN",
    "wecom": "zh-CN",
    "wechat_official": "zh-CN",
    "qq": "zh-CN",
}


def normalize_locale(value: str | None) -> str:
    """Normalize a locale string. Maps Chinese variants to zh-CN, C/POSIX to en, else passes through."""
    if not value or not str(value).strip():
        return DEFAULT_LOCALE

    raw = str(value).strip().replace("_", "-")
    lower = raw.lower()

    if lower in {"c", "posix"}:
        return DEFAULT_LOCALE

    if lower.startswith("zh"):
        return "zh-CN"

    return raw


def resolve_locale(
    *,
    explicit: str | None = None,
    metadata_locale: str | None = None,
    platform_locale: str | None = None,
    user_locale: str | None = None,
    channel: str | None = None,
) -> str:
    """Resolve locale using priority: explicit > metadata > platform > user > platform-default > en."""
    for candidate in (explicit, metadata_locale, platform_locale, user_locale):
        if candidate:
            return normalize_locale(candidate)

    if channel:
        platform_default = PLATFORM_DEFAULT_LOCALES.get(channel.lower())
        if platform_default:
            return normalize_locale(platform_default)

    env_locale = os.environ.get("MYRM_LOCALE")
    if env_locale:
        return normalize_locale(env_locale)

    return DEFAULT_LOCALE


def is_chinese(locale: str | None) -> bool:
    """Return True when locale resolves to Chinese."""
    return normalize_locale(locale) == "zh-CN"


def catalog_locale(locale: str | None) -> str:
    """Map any locale to a catalog file key."""
    normalized = normalize_locale(locale)
    if normalized == "zh-CN":
        return "zh-CN"
    return normalized
