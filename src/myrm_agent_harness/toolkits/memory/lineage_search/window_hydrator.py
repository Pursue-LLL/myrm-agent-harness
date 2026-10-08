"""Hydrates surviving search hits with two-tier adaptive detail:.

[INPUT]
- toolkits.memory.lineage_search.models::ConversationMessage, HydratedSessionHit, RawSearchHit, SessionMeta
  (POS: Types and models for lineage search.)

[OUTPUT]
- AdaptiveWindowHydrator: Hydrates surviving search hits with two-tier adaptive detail:.

[POS]
Hydrates surviving search hits with two-tier adaptive detail:.
"""

# [POS]: myrm_agent_harness/toolkits/memory/lineage_search/window_hydrator.py
# [INPUT]: Deduplicated hits, conversation message storage, window configuration
# [OUTPUT]: Adaptive hydration expanding Top 1 full window and Top 2-N compact cards

from collections.abc import Sequence

from myrm_agent_harness.toolkits.memory.lineage_search.models import (
    ConversationMessage,
    HydratedSessionHit,
    RawSearchHit,
    SessionMeta,
)

_MAX_CONTENT_CHARS = 2000


def _truncate_message(msg: ConversationMessage, max_chars: int = _MAX_CONTENT_CHARS) -> ConversationMessage:
    """Cap message text length to prevent unbounded token explosion."""
    if len(msg.content) <= max_chars:
        return msg
    truncated = msg.content[:max_chars].rstrip() + "\n...[truncated for token economy]"
    return ConversationMessage(
        message_id=msg.message_id,
        session_id=msg.session_id,
        role=msg.role,
        content=truncated,
        created_at=msg.created_at,
        sequence_num=msg.sequence_num,
    )


class AdaptiveWindowHydrator:
    """Hydrates surviving search hits with two-tier adaptive detail:

    - Rank 1 (Top 1): Full anchored window (±5 messages) + bookends (start/end 3)
    - Rank 2-N: Compact single-message card, reducing prompt tokens by >70%.
    """

    def __init__(self, anchor_window: int = 5, bookend_count: int = 3) -> None:
        self._anchor_window = anchor_window
        self._bookend_count = bookend_count

    def hydrate(
        self,
        deduped_candidates: Sequence[tuple[RawSearchHit, str]],
        session_metas: dict[str, SessionMeta],
        message_store: dict[str, list[ConversationMessage]],
    ) -> list[HydratedSessionHit]:
        """Produce hydrated hits applying top-1 full window vs top-N compact card policy."""
        hydrated_results: list[HydratedSessionHit] = []

        for rank_idx, (hit, lineage_root) in enumerate(deduped_candidates, start=1):
            sid = hit.session_id
            mid = hit.message_id
            meta = session_metas.get(sid)
            title = meta.title if meta else ""
            source = (meta.source.value if meta else hit.source.value)
            messages = message_store.get(sid, [])

            # Locate anchor index
            anchor_idx = -1
            for idx, m in enumerate(messages):
                if m.message_id == mid:
                    anchor_idx = idx
                    break

            deep_link = f"@session:{sid}#msg_{mid}"
            snippet = hit.content_snippet or (messages[anchor_idx].content[:150] if anchor_idx >= 0 else "")

            # Rank 1 receives full window hydration
            if rank_idx == 1 and anchor_idx >= 0 and messages:
                detail_level = "full"
                start_w = max(0, anchor_idx - self._anchor_window)
                end_w = min(len(messages), anchor_idx + self._anchor_window + 1)
                window_msgs = [_truncate_message(m) for m in messages[start_w:end_w]]
                bookend_start = [_truncate_message(m) for m in messages[: self._bookend_count]]
                bookend_end = [_truncate_message(m) for m in messages[-self._bookend_count :]]
                msgs_before = start_w
                msgs_after = max(0, len(messages) - end_w)
            else:
                # Rank 2+ receives compact card detail
                detail_level = "compact"
                matched_msg = (
                    [_truncate_message(messages[anchor_idx])]
                    if anchor_idx >= 0
                    else [ConversationMessage(mid, sid, hit.role, snippet, "")]
                )
                window_msgs = matched_msg
                bookend_start = []
                bookend_end = []
                msgs_before = anchor_idx if anchor_idx >= 0 else 0
                msgs_after = max(0, len(messages) - anchor_idx - 1) if anchor_idx >= 0 else 0

            hydrated_results.append(
                HydratedSessionHit(
                    session_id=sid,
                    lineage_root_id=lineage_root,
                    title=title,
                    source=source,
                    score=round(hit.score, 4),
                    match_message_id=mid,
                    snippet=snippet,
                    detail_level=detail_level,
                    deep_link=deep_link,
                    window_messages=window_msgs,
                    bookend_start=bookend_start,
                    bookend_end=bookend_end,
                    messages_before=msgs_before,
                    messages_after=msgs_after,
                )
            )

        return hydrated_results
