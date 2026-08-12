"""Third-party content extractors (fast-path, no browser required).

Aggregates the WeChat / Bilibili / YouTube extractors behind
``toolkits.web_fetch.extractors``. Each extractor owns parsing for a single
source and is used as a fast-path by the FetchEngine before L2/L3 browser
fallback.

[INPUT]
- (none)

[OUTPUT]
- extract_weixin_article / is_weixin_article_url / get_weixin_request_headers
- extract_bilibili_subtitle / is_bilibili_url
- extract_youtube_transcript / is_youtube_url
"""

from .bilibili_extractor import extract_bilibili_subtitle, is_bilibili_url
from .weixin_extractor import (
    extract_weixin_article,
    get_weixin_request_headers,
    is_weixin_article_url,
)
from .youtube_extractor import extract_youtube_transcript, is_youtube_url

__all__ = [
    "extract_bilibili_subtitle",
    "extract_weixin_article",
    "extract_youtube_transcript",
    "get_weixin_request_headers",
    "is_bilibili_url",
    "is_weixin_article_url",
    "is_youtube_url",
]
