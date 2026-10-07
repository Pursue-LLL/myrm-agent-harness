# ============================================================================
# # PinnedContextRetentionProcessor - Zero-Pruning Pins & Inspector Card (Item 146)
# # Protects user-pinned messages and architectural decisions across compactions,
# # and formats structured transparency inspector cards for frontend inspection.
# ============================================================================

from __future__ import annotations

import time
import uuid

from langchain_core.messages import SystemMessage

from myrm_agent_harness.agent.context_management.pipeline.base import (
    BaseProcessor,
    ProcessorContext,
)

from .context_pin_types import (
    CompactionInspectorCardData,
    PinnedContextItem,
    PinnedItemType,
)


class PinnedContextRetentionProcessor(BaseProcessor):
    """Guarantees zero-pruning preservation of pinned contexts and constructs inspector cards."""

    @property
    def name(self) -> str:
        return "pinned_context_retention_processor"

    def should_process(self, context: ProcessorContext) -> bool:
        """Determines if context contains pins or requires compaction inspector formatting."""
        has_pins = (
            "pinned_items" in context.metadata
            or "pinned_message_ids" in context.metadata
            or any(
                bool(getattr(msg, "additional_kwargs", {}).get("is_pinned", False))
                for msg in context.messages
            )
        )
        has_compaction_event = context.tokens_saved > 0 or context.structured_summary is not None
        return has_pins or has_compaction_event

    def process(self, context: ProcessorContext) -> ProcessorContext:
        """Executes zero-pruning verification and attaches compaction transparency card."""
        pinned_items = self._extract_pinned_items(context)

        # 1. Zero-Pruning Verification & Restoration
        restored_count = self._ensure_pinned_messages_present(context, pinned_items)

        # 2. Construct Transparent Compaction Inspector Card if compaction occurred
        if context.tokens_saved > 0 or context.structured_summary is not None:
            card = self.build_compaction_inspector_card(context, pinned_items)
            context.metadata["compaction_inspector_card"] = card.to_dict()

        context.operations.append(f"pinned_context_retention(pins={len(pinned_items)}, restored={restored_count})")
        return context

    def _extract_pinned_items(self, context: ProcessorContext) -> list[PinnedContextItem]:
        """Gathers pinned items from metadata and message additional_kwargs."""
        items: list[PinnedContextItem] = []

        # From metadata
        raw_items = context.metadata.get("pinned_items")
        if isinstance(raw_items, list):
            for it in raw_items:
                if isinstance(it, PinnedContextItem):
                    items.append(it)

        # From pinned_message_ids list in metadata
        pinned_ids = context.metadata.get("pinned_message_ids")
        if isinstance(pinned_ids, (list, set)):
            target_ids = {str(x) for x in pinned_ids}
            for msg in context.messages:
                mid = str(getattr(msg, "id", "") or getattr(msg, "additional_kwargs", {}).get("message_id", ""))
                if mid and mid in target_ids and not any(pi.target_id == mid for pi in items):
                    items.append(
                        PinnedContextItem(
                            pin_id=f"pin-{mid}",
                            item_type=PinnedItemType.MESSAGE,
                            content=str(msg.content),
                            target_id=mid,
                            title=f"Pinned Message ({getattr(msg, 'type', 'message')})",
                        )
                    )

        # From message additional_kwargs["is_pinned"]
        for msg in context.messages:
            kwargs = getattr(msg, "additional_kwargs", {})
            if kwargs.get("is_pinned") is True:
                mid = str(getattr(msg, "id", "") or kwargs.get("message_id", f"msg-{uuid.uuid4().hex[:6]}"))
                if not any(pi.target_id == mid for pi in items):
                    items.append(
                        PinnedContextItem(
                            pin_id=f"pin-{mid}",
                            item_type=PinnedItemType.MESSAGE,
                            content=str(msg.content),
                            target_id=mid,
                            title="Pinned Message",
                        )
                    )

        return items

    def _ensure_pinned_messages_present(
        self,
        context: ProcessorContext,
        pinned_items: list[PinnedContextItem],
    ) -> int:
        """Verifies all pinned items survive in the context, restoring missing ones."""
        restored = 0
        existing_contents = {str(m.content) for m in context.messages}

        for pin in pinned_items:
            if pin.content not in existing_contents:
                # Restore pinned item as a protected SystemMessage anchor block
                anchor = SystemMessage(
                    content=f"📌 [PINNED CONTEXT: {pin.title}]\n{pin.content}",
                    additional_kwargs={"is_pinned": True, "protected_by_pin": True, "pin_id": pin.pin_id},
                )
                # Insert right after root system message if one exists, else at index 0
                insert_idx = 1 if context.messages and isinstance(context.messages[0], SystemMessage) else 0
                context.messages.insert(insert_idx, anchor)
                existing_contents.add(pin.content)
                restored += 1
            else:
                # Mark existing message as protected
                for msg in context.messages:
                    if str(msg.content) == pin.content:
                        if not hasattr(msg, "additional_kwargs") or msg.additional_kwargs is None:
                            msg.additional_kwargs = {}
                        msg.additional_kwargs["protected_by_pin"] = True

        return restored

    def build_compaction_inspector_card(
        self,
        context: ProcessorContext,
        pinned_items: list[PinnedContextItem],
    ) -> CompactionInspectorCardData:
        """Builds a structured transparent inspection card for frontend rendering."""
        saved_tokens = max(0, context.tokens_saved)
        # Approximate pre_tokens from saved_tokens + current estimated tokens
        current_len = sum(len(str(m.content)) for m in context.messages)
        post_tokens = max(1, current_len // 4)
        pre_tokens = post_tokens + saved_tokens
        savings_ratio = float(saved_tokens / pre_tokens) if pre_tokens > 0 else 0.0

        summary_text = ""
        key_decisions: list[str] = []
        if context.structured_summary is not None:
            summary_text = getattr(context.structured_summary, "summary", "") or str(context.structured_summary)
            raw_decisions = getattr(context.structured_summary, "key_decisions", [])
            if isinstance(raw_decisions, list):
                key_decisions = [str(d) for d in raw_decisions]

        if not summary_text:
            summary_text = "历史对话上下文已成功压缩并精炼提纯。"

        preview = [f"📌 [{pi.item_type}] {pi.content[:60]}..." for pi in pinned_items]

        return CompactionInspectorCardData(
            card_id=f"card-compact-{uuid.uuid4().hex[:8]}",
            chat_id=context.chat_id or "default-chat",
            pre_tokens=pre_tokens,
            post_tokens=post_tokens,
            saved_tokens=saved_tokens,
            savings_ratio=savings_ratio,
            compacted_turns_count=len(context.operations),
            preserved_pinned_count=len(pinned_items),
            structured_summary_text=summary_text,
            key_decisions=key_decisions,
            pinned_items_preview=preview,
            is_user_editable=True,
            created_at=time.time(),
        )
