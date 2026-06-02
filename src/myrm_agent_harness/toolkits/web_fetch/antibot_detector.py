"""Anti-bot and error page detection for crawl results.

Three-tier layered detection to determine if a crawl was blocked
by anti-bot protection or returned an error page.

Detection philosophy (from crawl4ai):
  false positives are cheap (the fallback/degradation rescues them),
  false negatives are catastrophic (Agent gets garbage content).
  Err on the side of detection.

Tiers:
  - Tier 1: High-confidence WAF structural markers → any page size
  - Tier 2: Medium-confidence generic patterns → short pages only
  - Tier 3: Structural integrity → catches silent blocks / empty shells

[INPUT]
- (none)

[OUTPUT]
- is_blocked: Detect if a crawl result was blocked by anti-bot protecti...

[POS]
Anti-bot and error page detection for crawl results.
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Tier 1: High-confidence structural markers (any page size)
# Unique to block pages; virtually never appear in real content.
# ---------------------------------------------------------------------------
_TIER1_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"Reference\s*#\s*[\d]+\.[0-9a-f]+\.\d+\.[0-9a-f]+", re.I), "Akamai block (Reference #)"),
    (re.compile(r"Pardon\s+Our\s+Interruption", re.I), "Akamai challenge"),
    (re.compile(r"challenge-form.*?__cf_chl_f_tk=", re.I | re.DOTALL), "Cloudflare challenge form"),
    (re.compile(r'<span\s+class="cf-error-code">\d{4}</span>', re.I), "Cloudflare firewall block"),
    (re.compile(r"/cdn-cgi/challenge-platform/\S+orchestrate", re.I), "Cloudflare JS challenge"),
    (re.compile(r"window\._pxAppId\s*=", re.I), "PerimeterX block"),
    (re.compile(r"captcha\.px-cdn\.net", re.I), "PerimeterX captcha"),
    (re.compile(r"captcha-delivery\.com", re.I), "DataDome captcha"),
    (re.compile(r"_Incapsula_Resource", re.I), "Imperva/Incapsula block"),
    (re.compile(r"Incapsula\s+incident\s+ID", re.I), "Imperva/Incapsula incident"),
    (re.compile(r"Sucuri\s+WebSite\s+Firewall", re.I), "Sucuri firewall block"),
    (re.compile(r"KPSDK\.scriptStart\s*=\s*KPSDK\.now\(\)", re.I), "Kasada challenge"),
    (re.compile(r"blocked\s+by\s+network\s+security", re.I), "Network security block"),
]

# ---------------------------------------------------------------------------
# Tier 2: Medium-confidence patterns — only short pages (< 10 KB)
# These terms appear in real content, so we gate on page size.
# ---------------------------------------------------------------------------
_TIER2_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"Access\s+Denied", re.I), "Access Denied on short page"),
    (re.compile(r"Checking\s+your\s+browser", re.I), "Cloudflare browser check"),
    (re.compile(r"<title>\s*Just\s+a\s+moment", re.I), "Cloudflare interstitial"),
    (re.compile(r'class=["\']g-recaptcha["\']', re.I), "reCAPTCHA on block page"),
    (re.compile(r'class=["\']h-captcha["\']', re.I), "hCaptcha on block page"),
    (re.compile(r"Access\s+to\s+This\s+Page\s+Has\s+Been\s+Blocked", re.I), "PerimeterX block page"),
    (re.compile(r"blocked\s+by\s+security", re.I), "Blocked by security"),
    (re.compile(r"Request\s+unsuccessful", re.I), "Request unsuccessful (Imperva)"),
]

_TIER2_MAX_SIZE = 10_000

# ---------------------------------------------------------------------------
# Tier 3: Structural integrity — silent blocks, empty shells
# ---------------------------------------------------------------------------
_STRUCTURAL_MAX_SIZE = 50_000
_CONTENT_ELEMENTS_RE = re.compile(
    r"<(?:p|h[1-6]|article|section|li|td|a|pre)\b",
    re.I,
)
_SCRIPT_TAG_RE = re.compile(r"<script\b", re.I)
_STYLE_TAG_RE = re.compile(r"<style\b[\s\S]*?</style>", re.I)
_SCRIPT_BLOCK_RE = re.compile(r"<script\b[\s\S]*?</script>", re.I)
_TAG_RE = re.compile(r"<[^>]+>")
_BODY_RE = re.compile(r"<body\b", re.I)

# ---------------------------------------------------------------------------
# Error page title patterns
# ---------------------------------------------------------------------------
_ERROR_TITLE_RE = re.compile(
    r"\b(?:404|not\s+found|page\s+not\s+found|error|access\s+denied"
    r"|forbidden|unauthorized|50[023]|bad\s+gateway"
    r"|service\s+unavailable|temporarily\s+unavailable)\b",
    re.I,
)

_ERROR_CONTENT_KEYWORDS = frozenset(
    {
        "file not found",
        "page does not exist",
        "page not found",
        "access denied",
        "permission denied",
        "forbidden",
        "error occurred",
        "something went wrong",
        "oops",
    }
)

# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------
_BLOCK_PAGE_MAX_SIZE = 5_000
_EMPTY_CONTENT_THRESHOLD = 100
_SNIPPET_SIZE = 15_000
_DEEP_SCAN_THRESHOLD = 15_000
_DEEP_SCAN_LIMIT = 500_000
_DEEP_SNIPPET_SIZE = 30_000


def _looks_like_data(html: str) -> bool:
    """Check if content looks like a JSON/XML API response."""
    stripped = html.strip()
    if not stripped:
        return False
    if stripped[0] in ("{", "["):
        return True
    if stripped[:10].lower().startswith(("<html", "<!")):
        return bool(re.search(r"<body[^>]*>\s*<pre[^>]*>\s*[{\[]", stripped[:500], re.I))
    return stripped[0] == "<"


def _structural_integrity_check(html: str) -> tuple[bool, str]:
    """Tier 3: Catch pages that pass pattern detection but are structurally broken."""
    html_len = len(html)
    if html_len > _STRUCTURAL_MAX_SIZE or _looks_like_data(html):
        return False, ""

    if not _BODY_RE.search(html):
        return True, f"Structural: no <body> tag ({html_len} bytes)"

    body_match = re.search(r"<body\b[^>]*>([\s\S]*)</body>", html, re.I)
    body_content = body_match.group(1) if body_match else html
    stripped = _SCRIPT_BLOCK_RE.sub("", body_content)
    stripped = _STYLE_TAG_RE.sub("", stripped)
    visible_text = _TAG_RE.sub("", stripped).strip()
    visible_len = len(visible_text)

    signals: list[str] = []

    if visible_len < 50:
        signals.append("minimal_text")

    content_elements = len(_CONTENT_ELEMENTS_RE.findall(html))
    if content_elements == 0:
        signals.append("no_content_elements")

    script_count = len(_SCRIPT_TAG_RE.findall(html))
    if script_count > 0 and content_elements == 0 and visible_len < 100:
        signals.append("script_heavy_shell")

    signal_count = len(signals)
    if signal_count >= 2:
        return True, f"Structural: {', '.join(signals)} ({html_len} bytes, {visible_len} chars visible)"
    if signal_count == 1 and html_len < _BLOCK_PAGE_MAX_SIZE:
        return True, f"Structural: {signals[0]} on small page ({html_len} bytes, {visible_len} chars visible)"

    return False, ""


def _check_error_page(title: str | None, content: str | None) -> tuple[bool, str]:
    """Check for standard error pages (404, 500, etc.)."""
    if title and _ERROR_TITLE_RE.search(title):
        return True, f"Error page title: {title}"

    if content and len(content) < 100:
        content_lower = content.lower()
        for keyword in _ERROR_CONTENT_KEYWORDS:
            if keyword in content_lower:
                return True, f"Error page content ({len(content)} chars)"

    return False, ""


def is_blocked(
    status_code: int | None,
    html: str | None,
    *,
    title: str | None = None,
) -> tuple[bool, str]:
    """Detect if a crawl result was blocked by anti-bot protection or is an error page.

    Uses layered detection to maximize coverage while minimizing false positives.

    Returns:
        (is_blocked, reason). reason is empty string when not blocked.
    """
    html = html or ""
    html_len = len(html)

    if status_code == 429:
        return True, "HTTP 429 Too Many Requests"

    # --- Tier 1: High-confidence patterns (any page size) ---
    snippet = html[:_SNIPPET_SIZE]
    if snippet:
        for pattern, reason in _TIER1_PATTERNS:
            if pattern.search(snippet):
                return True, reason

    # Large-page deep scan: strip scripts/styles and re-check Tier 1
    if html_len > _DEEP_SCAN_THRESHOLD:
        stripped_html = _SCRIPT_BLOCK_RE.sub("", html[:_DEEP_SCAN_LIMIT])
        stripped_html = _STYLE_TAG_RE.sub("", stripped_html)
        deep_snippet = stripped_html[:_DEEP_SNIPPET_SIZE]
        for pattern, reason in _TIER1_PATTERNS:
            if pattern.search(deep_snippet):
                return True, reason

    # --- HTTP 403/503: always blocked for non-data HTML ---
    if status_code in (403, 503) and not _looks_like_data(html):
        if html_len < _EMPTY_CONTENT_THRESHOLD:
            return True, f"HTTP {status_code} with near-empty response ({html_len} bytes)"
        if html_len > _TIER2_MAX_SIZE:
            stripped_html = _SCRIPT_BLOCK_RE.sub("", html[:_DEEP_SCAN_LIMIT])
            stripped_html = _STYLE_TAG_RE.sub("", stripped_html)
            check_snippet = stripped_html[:_DEEP_SNIPPET_SIZE]
        else:
            check_snippet = snippet
        for pattern, reason in _TIER2_PATTERNS:
            if pattern.search(check_snippet):
                return True, f"{reason} (HTTP {status_code}, {html_len} bytes)"
        return True, f"HTTP {status_code} with HTML content ({html_len} bytes)"

    # --- Tier 2: medium-confidence on other 4xx/5xx + short page ---
    if status_code and status_code >= 400 and html_len < _TIER2_MAX_SIZE:
        for pattern, reason in _TIER2_PATTERNS:
            if pattern.search(snippet):
                return True, f"{reason} (HTTP {status_code}, {html_len} bytes)"

    # --- HTTP 200 + near-empty (JS-rendered empty page) ---
    if status_code == 200:
        stripped = html.strip()
        if len(stripped) < _EMPTY_CONTENT_THRESHOLD and not _looks_like_data(html):
            return True, f"Near-empty content ({len(stripped)} bytes) with HTTP 200"

    # --- Tier 3: Structural integrity ---
    blocked, reason = _structural_integrity_check(html)
    if blocked:
        return blocked, reason

    # --- Error page detection ---
    blocked, reason = _check_error_page(title, html if html_len < 200 else None)
    if blocked:
        return blocked, reason

    return False, ""
