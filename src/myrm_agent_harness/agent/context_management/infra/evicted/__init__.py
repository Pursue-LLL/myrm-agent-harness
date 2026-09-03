"""UECD evicted content subpackage — persist, read, and FilterProcessor delegate.

[INPUT]
- See child modules: content, reader, persister, markers

[OUTPUT]
- Public facade re-exports for harness, server, and tests

[POS]
Domain subpackage for `.context/{chat_id}/evicted/` delivery (infra layer).
"""

from myrm_agent_harness.agent.context_management.infra.evicted.content import (
    EVICTED_BASENAME_PATTERN,
    MAX_PREVIEW_STDOUT_CHARS,
    MAX_STORED_CHARS,
    EvictedPersistResult,
    EvictedRefPayload,
    build_delivery_footer,
    build_evicted_basename,
    build_evicted_ref_payload,
    cap_content_for_storage,
    emit_evicted_ref,
    normalize_delivery_chat_id,
    persist_evicted_content,
    sanitize_evicted_source,
    write_evicted_content_sync,
)
from myrm_agent_harness.agent.context_management.infra.evicted.markers import (
    probe_storage_cap_from_tail,
)
from myrm_agent_harness.agent.context_management.infra.evicted.persister import (
    persist_large_tool_output,
)
from myrm_agent_harness.agent.context_management.infra.evicted.reader import (
    EvictedFileMeta,
    EvictedLineRange,
    count_lines_in_text,
    read_evicted_file_meta,
    read_evicted_line_range,
)

__all__ = [
    "EVICTED_BASENAME_PATTERN",
    "MAX_PREVIEW_STDOUT_CHARS",
    "MAX_STORED_CHARS",
    "EvictedFileMeta",
    "EvictedLineRange",
    "EvictedPersistResult",
    "EvictedRefPayload",
    "build_delivery_footer",
    "build_evicted_basename",
    "build_evicted_ref_payload",
    "cap_content_for_storage",
    "count_lines_in_text",
    "emit_evicted_ref",
    "normalize_delivery_chat_id",
    "persist_evicted_content",
    "persist_large_tool_output",
    "probe_storage_cap_from_tail",
    "read_evicted_file_meta",
    "read_evicted_line_range",
    "sanitize_evicted_source",
    "write_evicted_content_sync",
]
