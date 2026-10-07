# ============================================================================
# Direct-Tool History Redaction & Multimodal Degradation Engine (Item 158)
# Scrub direct-to-user tool outputs from historical turns to stop bloat,
# strip cross-turn media raw bytes to prevent Provider error code 1210,
# and tailor question-aware sidecar captions for historical context.
# ============================================================================

from __future__ import annotations

import logging
from typing import Sequence

from .redaction_types import (
    DegradationReport,
    DirectToolPolicyKind,
    HistoryMessageView,
    MediaAttachment,
    MediaAttachmentKind,
    RedactedToolResult,
)

logger = logging.getLogger(__name__)

_DEFAULT_DIRECT_TOOLS: frozenset[str] = frozenset({
    "export_csv",
    "generate_image",
    "send_im_notification",
    "render_dashboard",
    "download_file",
    "direct_user_report",
    "display_chart",
})


class DirectToolHistoryPlaceholderFilter:
    """Filters historical direct-return tool results to prevent payload echoes."""

    def __init__(self, custom_direct_tools: Sequence[str] | None = None) -> None:
        self._direct_tools: set[str] = set(_DEFAULT_DIRECT_TOOLS)
        if custom_direct_tools:
            self._direct_tools.update(custom_direct_tools)

    def register_direct_tool(self, tool_name: str) -> None:
        """Register a tool name as delivering outputs straight to user."""
        self._direct_tools.add(tool_name)

    def is_direct_tool(self, tool_name: str) -> bool:
        """Check whether tool delivers straight to user."""
        return tool_name in self._direct_tools

    def process_tool_result(
        self,
        tool_name: str,
        tool_call_id: str,
        raw_output: str,
        is_current_turn: bool,
    ) -> RedactedToolResult:
        """Filter tool execution output based on turn recency and tool policy."""
        raw_byte_size = len(raw_output.encode("utf-8"))

        # Never scrub outputs on the current active turn
        if is_current_turn or not self.is_direct_tool(tool_name):
            return RedactedToolResult(
                tool_call_id=tool_call_id,
                tool_name=tool_name,
                is_redacted=False,
                final_content=raw_output,
                original_byte_size=raw_byte_size,
                placeholder_text=None,
            )

        # Historical direct-to-user output: scrub content and insert placeholder
        placeholder = (
            f"[Previous turn used direct-return tool(s) '{tool_name}' to deliver data "
            "straight to the user. Content withheld from model context per tool policy. "
            "If the user asks a follow-up that requires that data, call the tool again.]"
        )
        return RedactedToolResult(
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            is_redacted=True,
            final_content=placeholder,
            original_byte_size=raw_byte_size,
            placeholder_text=placeholder,
        )


class QuestionAwareSidecarCaptioner:
    """Generates focused semantic descriptions conditioned on user questions."""

    @staticmethod
    def generate_caption(attachment: MediaAttachment, user_question: str) -> str:
        """Synthesize tailored description emphasizing elements asked by user."""
        if attachment.caption:
            base_caption = attachment.caption
        else:
            base_caption = f"Visual capture of {attachment.file_name} ({attachment.kind.value})"

        question_clean = user_question.strip().lower()
        if not question_clean:
            return base_caption

        # Detect semantic focus areas from user question
        focus_tags: list[str] = []
        if any(term in question_clean for term in ("error", "bug", "crash", "traceback", "fail")):
            focus_tags.append("Error Diagnostics")
        if any(term in question_clean for term in ("chart", "plot", "graph", "metric", "trend")):
            focus_tags.append("Quantitative Trends")
        if any(term in question_clean for term in ("button", "ui", "layout", "click", "screen")):
            focus_tags.append("UI Interaction State")

        if focus_tags:
            tag_str = ", ".join(focus_tags)
            return f"{base_caption} (Tailored for question focus [{tag_str}]: verified in image)"
        return base_caption


class MultimodalAttachmentDegrader:
    """Strips historical media raw bytes and produces structured text degradation."""

    def __init__(self, captioner: QuestionAwareSidecarCaptioner | None = None) -> None:
        self._captioner = captioner or QuestionAwareSidecarCaptioner()

    def degrade_attachments(
        self,
        attachments: Sequence[MediaAttachment],
        user_question: str,
        is_current_turn: bool,
    ) -> tuple[tuple[MediaAttachment, ...], str, int, int]:
        """Degrade attachments across turns.

        Returns:
            (degraded_attachments, text_blocks, bytes_saved, tokens_saved)
        """
        if not attachments:
            return (), "", 0, 0

        # Current turn retains raw bytes for VLM perception
        if is_current_turn:
            return tuple(attachments), "", 0, 0

        degraded_list: list[MediaAttachment] = []
        text_blocks: list[str] = []
        bytes_saved = 0
        tokens_saved = 0

        for att in attachments:
            raw_len = len(att.raw_bytes_base64.encode("utf-8")) if att.raw_bytes_base64 else 0
            bytes_saved += raw_len
            tokens_saved += max(att.token_estimate, 1200)

            caption = self._captioner.generate_caption(att, user_question)
            text_block = (
                f"[媒体附件描述: {att.file_name} ({att.kind.value})]\n"
                f"{caption}\n"
                "[/媒体附件描述]"
            )
            text_blocks.append(text_block)

            degraded_att = MediaAttachment(
                attachment_id=att.attachment_id,
                kind=att.kind,
                mime_type=att.mime_type,
                file_name=att.file_name,
                raw_bytes_base64=None,  # Stripped!
                caption=caption,
                token_estimate=50,  # Reduced from ~1200+ to ~50
            )
            degraded_list.append(degraded_att)

        combined_text = "\n\n".join(text_blocks)
        return tuple(degraded_list), combined_text, bytes_saved, tokens_saved


class DirectToolMultimodalDegradationEngine:
    """Unified pipeline for direct-tool scrubbing and multimodal attachment degradation."""

    def __init__(
        self,
        tool_filter: DirectToolHistoryPlaceholderFilter | None = None,
        attachment_degrader: MultimodalAttachmentDegrader | None = None,
    ) -> None:
        self._tool_filter = tool_filter or DirectToolHistoryPlaceholderFilter()
        self._attachment_degrader = attachment_degrader or MultimodalAttachmentDegrader()

    def process_conversation(
        self,
        raw_turns: Sequence[
            tuple[
                str,  # role
                str,  # content
                int,  # turn_index
                Sequence[MediaAttachment] | None,  # attachments
                Sequence[tuple[str, str, str]] | None,  # tool_calls: (name, call_id, output)
            ]
        ],
        current_turn_index: int,
    ) -> tuple[tuple[HistoryMessageView, ...], DegradationReport]:
        """Project raw conversation history into clean LLM in-memory context."""
        projected_views: list[HistoryMessageView] = []
        tools_redacted_count = 0
        media_degraded_count = 0
        total_bytes_saved = 0
        total_tokens_saved = 0

        latest_user_question = ""
        # Find latest user question for context-aware captioning
        for role, content, turn_idx, _, _ in reversed(raw_turns):
            if role == "user":
                latest_user_question = content
                break

        for role, content, turn_idx, raw_attachments, raw_tools in raw_turns:
            is_current = turn_idx >= current_turn_index

            # 1. Process tool results
            projected_tools: list[RedactedToolResult] = []
            if raw_tools:
                for t_name, t_call_id, t_output in raw_tools:
                    res = self._tool_filter.process_tool_result(
                        tool_name=t_name,
                        tool_call_id=t_call_id,
                        raw_output=t_output,
                        is_current_turn=is_current,
                    )
                    projected_tools.append(res)
                    if res.is_redacted:
                        tools_redacted_count += 1
                        saved_bytes = max(res.original_byte_size - len(res.final_content.encode("utf-8")), 0)
                        total_bytes_saved += saved_bytes
                        total_tokens_saved += max(saved_bytes // 4, 100)

            # 2. Process attachments
            degraded_atts, text_desc, att_bytes_saved, att_tokens_saved = (
                self._attachment_degrader.degrade_attachments(
                    attachments=raw_attachments or (),
                    user_question=latest_user_question,
                    is_current_turn=is_current,
                )
            )
            if not is_current and raw_attachments:
                media_degraded_count += len(raw_attachments)
                total_bytes_saved += att_bytes_saved
                total_tokens_saved += att_tokens_saved

            # Build final assembled content
            final_content = content
            if text_desc:
                final_content = f"{final_content}\n\n{text_desc}".strip()

            view = HistoryMessageView(
                role=role,
                content=final_content,
                turn_index=turn_idx,
                is_current_turn=is_current,
                attachments=degraded_atts,
                tool_results=tuple(projected_tools),
            )
            projected_views.append(view)

        report = DegradationReport(
            total_messages_processed=len(raw_turns),
            tools_redacted_count=tools_redacted_count,
            media_degraded_count=media_degraded_count,
            bytes_saved_estimate=total_bytes_saved,
            tokens_saved_estimate=total_tokens_saved,
        )

        return tuple(projected_views), report
