"""Wiki raw ingress (browser clip + URL markdown assets).

[INPUT]
- ClipAssetInput / ClipIngressRequest / UrlMarkdownIngressRequest: 入库请求类型

[OUTPUT]
- publish_clip_ingress(): 浏览器剪切入库
- publish_url_markdown_ingress(): URL Markdown 入库
- ClipIngressResult: 入库结果

[POS]
Ingress surface for raw wiki assets — accepts browser clips and URL markdown,
validates them, and publishes into the wiki pipeline.
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
    UrlMarkdownIngressRequest,
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
    "UrlMarkdownIngressRequest",
    "load_wikiignore_patterns",
    "path_matches_wikiignore",
    "publish_clip_ingress",
    "publish_url_markdown_ingress",
    "wikiignore_path",
    "write_wikiignore_patterns",
]
