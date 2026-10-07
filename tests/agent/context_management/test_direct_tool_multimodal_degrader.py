# ============================================================================
# Unit Tests for Direct-Tool Redaction & Multimodal Degradation (Item 158)
# ============================================================================

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.context_management.multimodal_redaction import (
    DegradationReport,
    DirectToolHistoryPlaceholderFilter,
    DirectToolMultimodalDegradationEngine,
    HistoryMessageView,
    MediaAttachment,
    MediaAttachmentKind,
    MultimodalAttachmentDegrader,
    QuestionAwareSidecarCaptioner,
    RedactedToolResult,
)


def test_direct_tool_filter_preserves_current_turn_scrubs_history() -> None:
    """Validate direct tools are untouched on current turn but scrubbed in history."""
    filter_engine = DirectToolHistoryPlaceholderFilter(custom_direct_tools=["custom_export"])
    large_csv_payload = "col1,col2,col3\n" + "val1,val2,val3\n" * 500

    # 1. Current turn execution of direct tool: 100% preserved
    res_current = filter_engine.process_tool_result(
        tool_name="export_csv",
        tool_call_id="call_001",
        raw_output=large_csv_payload,
        is_current_turn=True,
    )
    assert res_current.is_redacted is False
    assert res_current.final_content == large_csv_payload
    assert res_current.placeholder_text is None

    # 2. Historical turn replay of direct tool: scrubbed to origin-preserving placeholder
    res_history = filter_engine.process_tool_result(
        tool_name="export_csv",
        tool_call_id="call_001",
        raw_output=large_csv_payload,
        is_current_turn=False,
    )
    assert res_history.is_redacted is True
    assert "direct-return tool(s) 'export_csv'" in res_history.final_content
    assert res_history.placeholder_text is not None
    assert len(res_history.final_content) < len(large_csv_payload)

    # 3. Standard scratchpad tool: never scrubbed
    res_scratchpad = filter_engine.process_tool_result(
        tool_name="run_shell",
        tool_call_id="call_002",
        raw_output="exit code 0: build success",
        is_current_turn=False,
    )
    assert res_scratchpad.is_redacted is False
    assert res_scratchpad.final_content == "exit code 0: build success"


def test_multimodal_attachment_degrader_current_vs_history() -> None:
    """Validate media bytes are preserved on current turn and stripped in history."""
    degrader = MultimodalAttachmentDegrader()
    img_attachment = MediaAttachment(
        attachment_id="att_101",
        kind=MediaAttachmentKind.IMAGE,
        mime_type="image/png",
        file_name="architecture_diag.png",
        raw_bytes_base64="iVBORw0KGgoAAAANSUhEUgAAAAUA...",
        caption="System architecture diagram",
        token_estimate=1500,
    )

    # Current turn: retain raw bytes, zero text injection
    degraded_cur, text_cur, bytes_saved_cur, tokens_saved_cur = degrader.degrade_attachments(
        attachments=[img_attachment],
        user_question="Explain the diagram.",
        is_current_turn=True,
    )
    assert len(degraded_cur) == 1
    assert degraded_cur[0].raw_bytes_base64 is not None
    assert text_cur == ""
    assert bytes_saved_cur == 0
    assert tokens_saved_cur == 0

    # Historical turn: strip raw bytes, inject structured text description
    degraded_hist, text_hist, bytes_saved_hist, tokens_saved_hist = degrader.degrade_attachments(
        attachments=[img_attachment],
        user_question="Explain the diagram.",
        is_current_turn=False,
    )
    assert len(degraded_hist) == 1
    assert degraded_hist[0].raw_bytes_base64 is None  # Stripped!
    assert "[媒体附件描述: architecture_diag.png (image)]" in text_hist
    assert "System architecture diagram" in text_hist
    assert bytes_saved_hist > 0
    assert tokens_saved_hist >= 1500


def test_question_aware_sidecar_captioner() -> None:
    """Validate caption synthesis extracts question focus for error/ui/trends."""
    captioner = QuestionAwareSidecarCaptioner()
    att = MediaAttachment(
        attachment_id="att_202",
        kind=MediaAttachmentKind.IMAGE,
        mime_type="image/jpeg",
        file_name="screenshot.jpg",
        caption="Dashboard main view",
    )

    # 1. Error focus question
    caption_err = captioner.generate_caption(att, "Why did the test fail with a crash traceback?")
    assert "Error Diagnostics" in caption_err

    # 2. Metric / Trend focus question
    caption_trend = captioner.generate_caption(att, "What is the monthly throughput trend in this chart?")
    assert "Quantitative Trends" in caption_trend

    # 3. UI interaction focus question
    caption_ui = captioner.generate_caption(att, "Where is the submit button located on the UI?")
    assert "UI Interaction State" in caption_ui


def test_direct_tool_multimodal_degradation_engine_pipeline() -> None:
    """End-to-end multi-turn pipeline verification with metrics report."""
    engine = DirectToolMultimodalDegradationEngine()

    att_img = MediaAttachment(
        attachment_id="att_1",
        kind=MediaAttachmentKind.IMAGE,
        mime_type="image/png",
        file_name="error_log.png",
        raw_bytes_base64="BASE64_LONG_PAYLOAD_BYTES" * 100,
        caption="Screenshot of crash stacktrace",
        token_estimate=1200,
    )

    raw_turns = [
        # Turn 1: Historical turn with user image and direct tool return
        (
            "user",
            "Please check this crash screenshot.",
            1,
            [att_img],
            None,
        ),
        (
            "assistant",
            "I will generate an analysis report and export the CSV.",
            1,
            None,
            [
                ("export_csv", "call_csv_1", "col1,col2\n" + "data1,data2\n" * 200),
                ("read_file", "call_read_1", "def main(): pass"),
            ],
        ),
        # Turn 2: Current active turn
        (
            "user",
            "Now fix the function definition.",
            2,
            None,
            None,
        ),
    ]

    projected_views, report = engine.process_conversation(raw_turns, current_turn_index=2)

    assert len(projected_views) == 3
    assert report.tools_redacted_count == 1  # export_csv in Turn 1 scrubbed
    assert report.media_degraded_count == 1  # error_log.png in Turn 1 degraded
    assert report.bytes_saved_estimate > 0
    assert report.tokens_saved_estimate > 0

    # Verify Turn 1 assistant tool output
    turn1_assistant = projected_views[1]
    csv_tool = [t for t in turn1_assistant.tool_results if t.tool_name == "export_csv"][0]
    read_tool = [t for t in turn1_assistant.tool_results if t.tool_name == "read_file"][0]

    assert csv_tool.is_redacted is True
    assert "direct-return tool(s) 'export_csv'" in csv_tool.final_content
    assert read_tool.is_redacted is False
    assert read_tool.final_content == "def main(): pass"

    # Verify Turn 1 user message text has injected degradation block
    turn1_user = projected_views[0]
    assert "[媒体附件描述: error_log.png" in turn1_user.content
    assert turn1_user.attachments[0].raw_bytes_base64 is None
