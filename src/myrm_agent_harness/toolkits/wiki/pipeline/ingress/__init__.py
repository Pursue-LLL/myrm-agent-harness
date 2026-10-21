"""Wiki raw ingress (browser clip + URL markdown assets).

[INPUT]
- .publish::publish_clip_ingress, publish_url_markdown_ingress (POS: clip + URL ingress writers)
- .types::ClipAssetInput, ClipIngressRequest, ClipIngressResult, ClipMode, MediaIngressRequest, UrlMarkdownIngressRequest, VideoUrlIngressRequest (POS: request/result contracts)
- .video_ingress::publish_media_ingress, publish_video_url_ingress (POS: media and video ingress)
- .wikiignore::load_wikiignore_patterns, path_matches_wikiignore, wikiignore_path (POS: ignore rule checks)

[OUTPUT]
- publish_clip_ingress, publish_url_markdown_ingress, publish_video_url_ingress, publish_media_ingress, ClipIngressRequest, ClipIngressResult

[POS]
Wiki raw ingress 模块入口。提供浏览器剪藏、网页 Markdown 抓取及多媒体转录的原始入库门面。
"""

from myrm_agent_harness.toolkits.wiki.pipeline.ingress.publish import (
    publish_clip_ingress,
    publish_url_markdown_ingress,
)
from myrm_agent_harness.toolkits.wiki.pipeline.ingress.types import (
    ClipAssetInput,
    ClipIngressRequest,
    ClipIngressResult,
    ClipMode,
    MediaIngressRequest,
    MediaKeyframe,
    MediaTranscriptSegment,
    UrlMarkdownIngressRequest,
    VideoUrlIngressRequest,
)
from myrm_agent_harness.toolkits.wiki.pipeline.ingress.video_ingress import (
    adaptive_merge_segments,
    format_timestamp,
    publish_media_ingress,
    publish_video_url_ingress,
)
from myrm_agent_harness.toolkits.wiki.pipeline.ingress.wikiignore import (
    load_wikiignore_patterns,
    path_matches_wikiignore,
    wikiignore_path,
    write_wikiignore_patterns,
)

__all__ = [
    "ClipAssetInput",
    "ClipIngressRequest",
    "ClipIngressResult",
    "ClipMode",
    "MediaIngressRequest",
    "MediaKeyframe",
    "MediaTranscriptSegment",
    "UrlMarkdownIngressRequest",
    "VideoUrlIngressRequest",
    "adaptive_merge_segments",
    "format_timestamp",
    "load_wikiignore_patterns",
    "path_matches_wikiignore",
    "publish_clip_ingress",
    "publish_media_ingress",
    "publish_url_markdown_ingress",
    "publish_video_url_ingress",
    "wikiignore_path",
    "write_wikiignore_patterns",
]
