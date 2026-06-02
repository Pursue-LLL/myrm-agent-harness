"""Page-level CAPTCHA detection for browser automation.

Detects blocking CAPTCHAs (Cloudflare Challenge, hCaptcha interstitial, etc.)
by inspecting the page HTML after navigation. Reuses proven regex patterns from
``antibot_detector`` and adds browser-specific Turnstile detection.

Detection philosophy: **conservative** — only triggers on full-page blocking
CAPTCHAs (challenge interstitials), NOT on embedded reCAPTCHA/hCaptcha widgets
within normal forms.  This avoids false-positive pauses on login pages that
contain a reCAPTCHA checkbox alongside real content.

[INPUT]
- patchright.async_api::Page (POS: Patchright page instance)

[OUTPUT]
- detect_captcha: Inspect a live page and return CaptchaInfo | None

[POS]
Page-level CAPTCHA detection for browser automation sessions.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from .protocols import CaptchaInfo, CaptchaType

if TYPE_CHECKING:
    from patchright.async_api import Page

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tier 1: High-confidence blocking CAPTCHA patterns (any page size)
# These patterns indicate the page IS a challenge page, not normal content.
# ---------------------------------------------------------------------------
_BLOCKING_CAPTCHA_PATTERNS: list[tuple[re.Pattern[str], str, CaptchaType]] = [
    # Cloudflare Challenge (classic JS challenge + managed challenge)
    (
        re.compile(r"challenge-form.*?__cf_chl_f_tk=", re.I | re.DOTALL),
        "Cloudflare challenge form",
        CaptchaType.CLOUDFLARE_CHALLENGE,
    ),
    (
        re.compile(r"/cdn-cgi/challenge-platform/\S+orchestrate", re.I),
        "Cloudflare JS challenge",
        CaptchaType.CLOUDFLARE_CHALLENGE,
    ),
    # Cloudflare Turnstile (iframe-based, newer generation)
    (
        re.compile(r'<iframe[^>]+src="[^"]*challenges\.cloudflare\.com/turnstile', re.I),
        "Cloudflare Turnstile iframe",
        CaptchaType.CLOUDFLARE_TURNSTILE,
    ),
    (
        re.compile(r"cf-turnstile", re.I),
        "Cloudflare Turnstile widget",
        CaptchaType.CLOUDFLARE_TURNSTILE,
    ),
    # PerimeterX captcha
    (
        re.compile(r"captcha\.px-cdn\.net", re.I),
        "PerimeterX captcha",
        CaptchaType.PERIMETERX,
    ),
    # DataDome captcha
    (
        re.compile(r"captcha-delivery\.com", re.I),
        "DataDome captcha",
        CaptchaType.DATADOME,
    ),
    # Kasada challenge
    (
        re.compile(r"KPSDK\.scriptStart\s*=\s*KPSDK\.now\(\)", re.I),
        "Kasada challenge",
        CaptchaType.KASADA,
    ),
    # Akamai challenge
    (
        re.compile(r"Pardon\s+Our\s+Interruption", re.I),
        "Akamai challenge",
        CaptchaType.AKAMAI,
    ),
    # Imperva / Incapsula
    (
        re.compile(r"_Incapsula_Resource", re.I),
        "Imperva/Incapsula block",
        CaptchaType.IMPERVA,
    ),
]

# ---------------------------------------------------------------------------
# Tier 2: Short-page-only CAPTCHA patterns (< _SHORT_PAGE_LIMIT bytes)
# On short pages these strongly indicate a challenge interstitial, but on
# large pages they may just be an embedded widget within real content.
# ---------------------------------------------------------------------------
_SHORT_PAGE_CAPTCHA_PATTERNS: list[tuple[re.Pattern[str], str, CaptchaType]] = [
    (
        re.compile(r"Checking\s+your\s+browser", re.I),
        "Cloudflare browser check",
        CaptchaType.CLOUDFLARE_CHALLENGE,
    ),
    (
        re.compile(r"<title>\s*Just\s+a\s+moment", re.I),
        "Cloudflare interstitial",
        CaptchaType.CLOUDFLARE_CHALLENGE,
    ),
    (
        re.compile(r'class=["\']g-recaptcha["\']', re.I),
        "reCAPTCHA on block page",
        CaptchaType.RECAPTCHA,
    ),
    (
        re.compile(r'class=["\']h-captcha["\']', re.I),
        "hCaptcha on block page",
        CaptchaType.HCAPTCHA,
    ),
]

_SHORT_PAGE_LIMIT = 10_000
_SCAN_SNIPPET_SIZE = 15_000


async def detect_captcha(page: Page) -> CaptchaInfo | None:
    """Inspect a live browser page for a blocking CAPTCHA.

    Performs HTML content analysis using proven regex patterns.
    Only fires on full-page blocking CAPTCHAs — embedded widgets are ignored.

    Performance: ~1–5 ms (page.content() from in-memory DOM + compiled regex).

    Args:
        page: The Patchright page to inspect.

    Returns:
        ``CaptchaInfo`` if a blocking CAPTCHA is detected, otherwise ``None``.
    """
    try:
        html = await page.content()
    except Exception as exc:
        logger.debug("CAPTCHA detector: failed to get page content: %s", exc)
        return None

    html_len = len(html)
    snippet = html[:_SCAN_SNIPPET_SIZE]

    # --- Tier 1: High-confidence blocking patterns (any page size) ---
    for pattern, reason, captcha_type in _BLOCKING_CAPTCHA_PATTERNS:
        if pattern.search(snippet):
            info = CaptchaInfo(
                captcha_type=captcha_type,
                reason=reason,
                blocking=True,
                confidence=1.0,
            )
            logger.warning(
                "CAPTCHA detected: %s (type=%s, page_size=%d)",
                reason,
                captcha_type,
                html_len,
            )
            return info

    # --- Tier 2: Short-page patterns (challenge interstitials) ---
    if html_len < _SHORT_PAGE_LIMIT:
        for pattern, reason, captcha_type in _SHORT_PAGE_CAPTCHA_PATTERNS:
            if pattern.search(snippet):
                info = CaptchaInfo(
                    captcha_type=captcha_type,
                    reason=reason,
                    blocking=True,
                    confidence=0.8,
                )
                logger.warning(
                    "CAPTCHA detected (short page): %s (type=%s, page_size=%d)",
                    reason,
                    captcha_type,
                    html_len,
                )
                return info

    return None
