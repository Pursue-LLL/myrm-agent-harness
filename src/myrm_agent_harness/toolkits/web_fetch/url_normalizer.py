"""URL 规范化 — 提升Cache命 in 率

移除 35+ 追踪Parameter（utm_*, fbclid, gclid, _hsenc, li_fat_id, ttclid  etc.），
统一Size写，规范化Path，SortQueryParameter。

Support平台：Google Analytics, Facebook, Google Ads, Bing, Mailchimp,
HubSpot, Adobe, LinkedIn, Twitter, TikTok  etc.。

[INPUT]
- (none)

[OUTPUT]
- normalize_url: Args:

[POS]
HubSpot, Adobe, LinkedIn, Twitter, TikTok  etc.。
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

_TRACKING_PARAMS = frozenset(
    {
        # Google Analytics
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_term",
        "utm_content",
        "_ga",
        "_gid",
        "_gac",
        # Facebook
        "fbclid",
        "fb_action_ids",
        "fb_action_types",
        "fb_source",
        # Google Ads
        "gclid",
        "gclsrc",
        # Bing
        "msclkid",
        # Mailchimp
        "mc_cid",
        "mc_eid",
        # HubSpot
        "_hsenc",
        "_hsmi",
        # Adobe
        "s_cid",
        # LinkedIn
        "li_fat_id",
        "li_source",
        # Twitter
        "twclid",
        # TikTok
        "ttclid",
        # Generic
        "ref",
        "referrer",
        "source",
    }
)


def normalize_url(url: str) -> str:
    """规范化 URL，提升Cache命 in 率

    操作：
    1. 移除追踪Parameter（utm_*, fbclid  etc.）
    2. 统一 scheme  is 小写
    3. 统一 netloc  is 小写
    4. 移除DefaultPort（:80, :443）
    5. 规范化Path（移除多余斜杠）
    6. QueryParameter按字母Sort

    Args:
        url: original URL

    Returns:
        规范化后  URL
    """
    parsed = urlparse(url)

    scheme = parsed.scheme.lower()
    netloc = parsed.netloc.lower()

    if (scheme == "http" and netloc.endswith(":80")) or (scheme == "https" and netloc.endswith(":443")):
        netloc = netloc.rsplit(":", 1)[0]

    path = parsed.path
    if path and "//" in path:
        path = "/".join(segment for segment in path.split("/") if segment)
        if not path.startswith("/"):
            path = "/" + path

    query_params = parse_qs(parsed.query, keep_blank_values=True)
    filtered_params = {k: v for k, v in query_params.items() if k not in _TRACKING_PARAMS}
    sorted_query = urlencode(sorted(filtered_params.items()), doseq=True)

    return urlunparse((scheme, netloc, path, parsed.params, sorted_query, ""))
