"""Unit tests for Adaptive Tool Result Content Router and Auto-Compactor."""

from __future__ import annotations

import json

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from myrm_agent_harness.agent.context_management.pipeline.base import ProcessorContext
from myrm_agent_harness.agent.context_management.pipeline.processors.adaptive_tool_result_compactor import (
    AdaptiveToolResultCompactor,
)
from myrm_agent_harness.agent.context_management.pipeline.processors.adaptive_tool_result_router_processor import (
    AdaptiveToolResultRouterProcessor,
)
from myrm_agent_harness.agent.context_management.pipeline.processors.content_router_types import (
    AdaptiveCompactorConfig,
    ToolResultFormatKind,
)
from myrm_agent_harness.agent.context_management.pipeline.processors.tool_result_content_sniffer import (
    ToolResultContentSniffer,
)


def test_tool_result_content_sniffer_multimodal_classification() -> None:
    # 1. JSON Array
    json_text = json.dumps([{"id": 1, "name": "a"}, {"id": 2, "name": "b"}])
    assert ToolResultContentSniffer.sniff(json_text) == ToolResultFormatKind.JSON_ARRAY

    # 2. Unified Diff
    diff_text = """diff --git a/file.py b/file.py
index abcdef..123456 100644
--- a/file.py
+++ b/file.py
@@ -1,3 +1,3 @@
-old line
+new line
"""
    assert ToolResultContentSniffer.sniff(diff_text) == ToolResultFormatKind.UNIFIED_DIFF

    # 3. Grep Matches
    grep_text = """src/core/app.py:12: def run():
src/core/app.py:15:     print("running")
src/core/app.py:20: def stop():
src/utils/log.py:5: def debug():
"""
    assert ToolResultContentSniffer.sniff(grep_text) == ToolResultFormatKind.GREP_MATCHES

    # 4. Tabular Markdown
    md_table = """| Name | Age |
| --- | --- |
| Alice | 30 |
| Bob | 25 |
"""
    assert ToolResultContentSniffer.sniff(md_table) == ToolResultFormatKind.TABULAR

    # 5. Repeated Logs
    rep_logs = """[INFO] 2026-10-07 Service heartbeating ok
[INFO] 2026-10-07 Service heartbeating ok
[INFO] 2026-10-07 Service heartbeating ok
[INFO] 2026-10-07 Service heartbeating ok
"""
    assert ToolResultContentSniffer.sniff(rep_logs) == ToolResultFormatKind.REPEATED_LOGS

    # 6. Plain Text
    plain_text = "Just a short message without any tabular or code structure."
    assert ToolResultContentSniffer.sniff(plain_text) == ToolResultFormatKind.PLAIN_TEXT


def test_compact_unified_diff_strips_git_metadata() -> None:
    diff_text = """diff --git a/service/handler.py b/service/handler.py
index a1b2c3d4..e5f6a7b8 100644
new file mode 100644
similarity index 100%
--- a/service/handler.py
+++ b/service/handler.py
@@ -10,6 +10,7 @@
 def process_event(event):
+    validate(event)
     return handle(event)
"""
    cfg = AdaptiveCompactorConfig(min_savings_chars=20)
    result = AdaptiveToolResultCompactor.compact(diff_text, config=cfg)

    assert result.is_compacted is True
    assert result.format_kind == ToolResultFormatKind.UNIFIED_DIFF
    assert "index a1b2c3d4..e5f6a7b8" not in result.compacted_text
    assert "new file mode 100644" not in result.compacted_text
    assert "similarity index 100%" not in result.compacted_text
    assert "validate(event)" in result.compacted_text
    assert result.saved_chars > 20


def test_compact_repeated_logs_folding() -> None:
    log_text = (
        "[INFO] Initializing system...\n"
        "[DEBUG] Waiting for connection heartbeat...\n"
        "[DEBUG] Waiting for connection heartbeat...\n"
        "[DEBUG] Waiting for connection heartbeat...\n"
        "[DEBUG] Waiting for connection heartbeat...\n"
        "[INFO] System ready.\n"
    )
    cfg = AdaptiveCompactorConfig(min_savings_chars=20, min_log_repeat_count=2)
    result = AdaptiveToolResultCompactor.compact(log_text, config=cfg)

    assert result.is_compacted is True
    assert result.format_kind == ToolResultFormatKind.REPEATED_LOGS
    assert "[repeated 4 times]: [DEBUG] Waiting for connection heartbeat..." in result.compacted_text
    assert "[INFO] Initializing system..." in result.compacted_text
    assert "[INFO] System ready." in result.compacted_text
    assert result.saved_chars > 30


def test_compact_grep_matches_path_grouping() -> None:
    grep_output = """src/core/auth.py:10:def authenticate(token: str):
src/core/auth.py:25:    token_validator.check(token)
src/core/auth.py:40:def revoke_session(session_id: str):
src/server/routes.py:100:auth_service.authenticate(req.token)
"""
    cfg = AdaptiveCompactorConfig(min_savings_chars=15, enable_grep_path_grouping=True)
    result = AdaptiveToolResultCompactor.compact(grep_output, config=cfg)

    assert result.is_compacted is True
    assert result.format_kind == ToolResultFormatKind.GREP_MATCHES
    assert "src/core/auth.py:" in result.compacted_text
    assert "  L10: def authenticate(token: str):" in result.compacted_text
    assert "  L25: token_validator.check(token)" in result.compacted_text
    assert "  L40: def revoke_session(session_id: str):" in result.compacted_text
    assert result.saved_chars >= 15


def test_compact_json_array_routes_to_gcf() -> None:
    records = [
        {"item_id": 1, "sku": "A100", "price": 99.0},
        {"item_id": 2, "sku": "A200", "price": 199.0},
        {"item_id": 3, "sku": "A300", "price": 299.0},
        {"item_id": 4, "sku": "A400", "price": 399.0},
    ]
    json_text = json.dumps(records)
    cfg = AdaptiveCompactorConfig(min_savings_chars=10)
    result = AdaptiveToolResultCompactor.compact(json_text, config=cfg)

    assert result.is_compacted is True
    assert result.format_kind == ToolResultFormatKind.JSON_ARRAY
    assert "_cols" in result.compacted_text
    assert "_rows" in result.compacted_text
    assert result.saved_chars > 10


def test_defensive_threshold_and_plain_text_bypass() -> None:
    # 1. Plain text bypass
    plain = "This is a simple status report with nothing special."
    res_plain = AdaptiveToolResultCompactor.compact(plain)
    assert res_plain.is_compacted is False
    assert res_plain.compacted_text == plain
    assert res_plain.bypass_reason == "plain_text_passthrough"

    # 2. Too small savings bypass
    tiny_diff = """diff --git a/a.txt b/a.txt
@@ -1 +1 @@
-a
+b
"""
    res_tiny = AdaptiveToolResultCompactor.compact(
        tiny_diff, config=AdaptiveCompactorConfig(min_savings_chars=100)
    )
    assert res_tiny.is_compacted is False
    assert res_tiny.compacted_text == tiny_diff


@pytest.mark.asyncio
async def test_adaptive_tool_result_router_processor_pipeline_integration() -> None:
    rep_logs = (
        "[POLL] status=pending\n"
        "[POLL] status=pending\n"
        "[POLL] status=pending\n"
        "[POLL] status=pending\n"
        "[POLL] status=pending\n"
    )
    messages = [
        HumanMessage(content="Check build log"),
        AIMessage(content="Checking status..."),
        ToolMessage(content=rep_logs, tool_call_id="call_build_poll_1"),
    ]

    proc = AdaptiveToolResultRouterProcessor(
        config=AdaptiveCompactorConfig(min_savings_chars=10, min_log_repeat_count=2)
    )
    context = ProcessorContext(messages=messages, user_query="Check build log")

    assert await proc.should_process(context) is True
    processed = await proc.process(context)

    # Tool message content was compacted
    compacted_log = str(processed.messages[2].content)
    assert "[repeated 5 times]: [POLL] status=pending" in compacted_log

    # Metadata metrics recorded
    assert processed.metadata.get("adaptive_compacted_count") == 1
    assert int(processed.metadata.get("adaptive_compacted_saved_chars", 0)) > 20
