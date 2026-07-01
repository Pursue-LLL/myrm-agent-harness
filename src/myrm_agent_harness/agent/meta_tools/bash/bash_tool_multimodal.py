"""Multimodal image return path for bash_code_execute_tool.

[INPUT]
- file_ops.utils.image_reader::read_image_as_content_blocks (POS: Image artifact converter)
- toolkits.code_execution.executors.base::require_executor (POS: ContextVar executor accessor)

[OUTPUT]
- MAX_IMAGES_PER_RETURN, maybe_build_image_blocks

[POS]
Inlines generated chart/screenshot artifacts as ContentBlocks when vision is enabled.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from typing import Final

logger = logging.getLogger(__name__)

MAX_IMAGES_PER_RETURN: Final[int] = 4


async def maybe_build_image_blocks(
    text_content: str,
    generated_files: list[str],
    context: Mapping[str, object],
) -> Sequence[object] | None:
    """Return ``[TextBlock, *ImageBlocks]`` when images can be returned multimodally."""
    if not generated_files:
        return None

    image_paths = [p for p in generated_files if _is_image_artifact(p)]
    if not image_paths:
        return None

    supports_vision = bool(context.get("supports_vision", False))
    if not supports_vision:
        return None

    from langchain_core.messages.content import ContentBlock, create_text_block

    from myrm_agent_harness.agent.meta_tools.file_ops.utils.image_reader import (
        read_image_as_content_blocks,
    )
    from myrm_agent_harness.toolkits.code_execution.executors.base import (
        require_executor,
    )

    executor = require_executor()
    blocks: list[ContentBlock] = [create_text_block(text_content)]
    appended_image = False

    inline_paths = image_paths[:MAX_IMAGES_PER_RETURN]
    overflow_paths = image_paths[MAX_IMAGES_PER_RETURN:]

    for image_path in inline_paths:
        try:
            image_result = await read_image_as_content_blocks(image_path, executor, supports_vision=True)
        except Exception as exc:
            logger.warning("bash_tool: failed to inline image %s: %s", image_path, exc)
            continue

        if isinstance(image_result, list):
            blocks.extend(image_result)
            appended_image = True
        elif isinstance(image_result, str):
            blocks.append(create_text_block(image_result))

    if not appended_image:
        return None

    if overflow_paths:
        paths_preview = ", ".join(overflow_paths[:8])
        suffix = "" if len(overflow_paths) <= 8 else f" (+{len(overflow_paths) - 8} more)"
        blocks.append(
            create_text_block(
                f"[bash_code_execute_tool] {len(overflow_paths)} additional image(s) "
                f"omitted from inline preview to keep the token budget bounded. "
                f"Use file_read_tool on demand: {paths_preview}{suffix}"
            )
        )

    return blocks


def _is_image_artifact(path: str) -> bool:
    """Detect image-like generated artifacts (delegates to image_reader)."""
    from myrm_agent_harness.agent.meta_tools.file_ops.utils.image_reader import (
        is_image_path,
    )

    return is_image_path(path)
