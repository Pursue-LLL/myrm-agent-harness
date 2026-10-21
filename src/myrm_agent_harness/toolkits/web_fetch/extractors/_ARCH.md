# extractors/

## Overview

Third-party content extractors — fast-path parsing for WeChat / Bilibili / YouTube,
used by the FetchEngine before L2/L3 browser fallback. Each extractor owns parsing
for a single source and may leverage optional deps (`youtube-transcript-api`) or the
SessionVault cookie store (Bilibili AI subtitles) without requiring a browser.

[INPUT]
- (none — pure parsing + fast-path helpers; `weixin_extractor` uses `..html_to_markdown`)

[OUTPUT]
- extract_weixin_article / get_weixin_request_headers / is_weixin_article_url
- extract_bilibili_subtitle / is_bilibili_url
- extract_youtube_transcript / is_youtube_url
- extract_x_post / is_x_url

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Aggregation facade — re-exports the extractors' public symbols. | ✅ |
| weixin_extractor.py | Core | WeChat Official Account fast-path — MicroMessenger UA + `#js_content` extraction (host `/s` URLs, data-src images, publish_time metadata); Browser fallback when blocked. | ✅ |
| bilibili_extractor.py | Core | Bilibili subtitle fast-path — public API + SessionVault cookie for AI subtitles; Browser fallback when unavailable. | ✅ |
| youtube_extractor.py | Core | YouTube transcript fast-path — `[web]` optional `youtube-transcript-api` + oEmbed metadata (title/author); HTML fallback when missing. | ✅ |
| x_extractor.py | Core | Twitter / X post fast-path — FxTwitter API / oEmbed structured extraction (text, metrics, media); Browser fallback on failure. | ✅ |

## Key Dependencies

- `..html_to_markdown` (WeChat article HTML → Markdown)
- `[web]` optional: `youtube-transcript-api`
- SessionVault cookie (Bilibili AI subtitles)

## Consumers

- `web_fetch/engine/fetch_mixin.py` / `web_fetch/engine/base.py` — fast-path before L2/L3 fallback
