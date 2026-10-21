"""OKF cognitive map — index.md, log.md, hot.md deterministic writers.

[INPUT]
- .events::WikiMapEvent, WikiMapEventType (POS: log event data contracts)
- .schema_writer::read_index_context, render_schema_markdown, write_schema_markdown (POS: schema writers)
- .snapshot::HotSnapshot, build_hot_snapshot (POS: hot snapshot generator)
- .writer::CognitiveMapRefreshResult, WikiCognitiveMapService, write_hot_markdown, write_index_markdown (POS: map writers)

[OUTPUT]
- CognitiveMapRefreshResult, HotSnapshot, WikiCognitiveMapService, WikiMapEvent, WikiMapEventType, read_hot_context, read_index_context

[POS]
OKF 认知地图模块入口。提供 wiki/index.md, wiki/log.md, wiki/hot.md 与 wiki/SCHEMA.md 的确定性免 LLM 构建与刷新。
"""

from __future__ import annotations

from myrm_agent_harness.toolkits.wiki.pipeline.cognitive_map.events import WikiMapEvent, WikiMapEventType
from myrm_agent_harness.toolkits.wiki.pipeline.cognitive_map.schema_writer import (
    read_index_context,
    render_schema_markdown,
    write_schema_markdown,
)
from myrm_agent_harness.toolkits.wiki.pipeline.cognitive_map.snapshot import HotSnapshot, build_hot_snapshot
from myrm_agent_harness.toolkits.wiki.pipeline.cognitive_map.writer import (
    CognitiveMapRefreshResult,
    WikiCognitiveMapService,
    append_log_entry,
    count_log_entries,
    hot_updated_at_iso,
    read_hot_context,
    read_log_context,
    write_hot_markdown,
    write_index_markdown,
)

__all__ = [
    "CognitiveMapRefreshResult",
    "HotSnapshot",
    "WikiCognitiveMapService",
    "WikiMapEvent",
    "WikiMapEventType",
    "append_log_entry",
    "build_hot_snapshot",
    "count_log_entries",
    "hot_updated_at_iso",
    "read_hot_context",
    "read_index_context",
    "read_log_context",
    "render_schema_markdown",
    "write_hot_markdown",
    "write_index_markdown",
    "write_schema_markdown",
]
