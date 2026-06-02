"""工具结果去重。

[INPUT]
- (none)

[OUTPUT]
- deduplicate_tool_results: function — deduplicate_tool_results

[POS]
Provides deduplicate_tool_results.
"""

from __future__ import annotations

import hashlib
import json

from langchain_core.messages import BaseMessage, ToolMessage

from myrm_agent_harness.utils.logger_utils import get_agent_logger
from myrm_agent_harness.utils.text_utils import get_token_count

from ..infra.schemas import ContextConfig

logger = get_agent_logger(__name__)


def deduplicate_tool_results(
    messages: list[BaseMessage], config: ContextConfig | None = None
) -> tuple[list[BaseMessage], int]:
    """对重复工具输出做反向引用去重。"""
    del config

    content_hashes: dict[str, tuple[int, str]] = {}
    tokens_saved = 0

    for i in range(len(messages) - 1, -1, -1):
        msg = messages[i]
        if not isinstance(msg, ToolMessage):
            continue

        content = msg.content if isinstance(msg.content, str) else json.dumps(msg.content)
        if content.startswith("COMPACTED:") or content.startswith("PRUNED:"):
            continue
        if content.startswith("[Duplicate tool output"):
            continue
        if len(content) < 200:
            continue

        content_hash = hashlib.md5(content.encode("utf-8", errors="replace")).hexdigest()[:12]
        if content_hash in content_hashes:
            prev_idx, prev_call_id = content_hashes[content_hash]
            ref_content = (
                f"[Duplicate tool output — same content as message #{prev_idx} (tool_call_id: {prev_call_id})]"
            )

            original_tokens = get_token_count(content)
            new_tokens = get_token_count(ref_content)
            tokens_saved += original_tokens - new_tokens

            msg.content = ref_content
            logger.info(
                "[去重] Message #%d 是重复内容，引用 #%d，节省 %d tokens", i, prev_idx, original_tokens - new_tokens
            )
        else:
            content_hashes[content_hash] = (i, msg.tool_call_id or "unknown")

    if tokens_saved > 0:
        logger.warning(" [去重] 去重完成，节省 %d tokens", tokens_saved)

    return messages, tokens_saved
