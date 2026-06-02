"""Archive restore read guard helpers.

[INPUT]
- context_management.infra.archive_reference::is_context_archive_path (POS: 归档路径判断)
- context_management.infra.session_lock::get_current_chat_id (POS: 当前会话上下文)
- context_management.tracking.task_metrics::ArchiveRefetchDecision, evaluate_archive_refetch_for_path (POS: 归档上下文读取预算)
- strategies.base::FileSystemStrategy (POS: 文件系统策略协议)
- operation_context::ViewRange (POS: 视图行范围)

[OUTPUT]
- evaluate_archive_full_read_before_content: pre-read archive full-restore budget guard.
- format_archive_restore_block: structured archive restore block formatter.
- parse_archive_restore_block_payload: parse the stable blocked payload from tool output.

[POS]
Archive restore guard. Blocks oversized full archive restores before file contents are loaded and formats stable blocked payloads.
"""

import json
import logging

from myrm_agent_harness.agent.context_management.infra.archive_reference import (
    is_context_archive_path,
)
from myrm_agent_harness.agent.context_management.infra.session_lock import (
    get_current_chat_id,
)
from myrm_agent_harness.agent.context_management.tracking.task_metrics import (
    ArchiveRefetchDecision,
    build_archive_restore_guidance,
    evaluate_archive_refetch_for_path,
)

from ..strategies.base import FileSystemStrategy
from .operation_context import ViewRange

logger = logging.getLogger(__name__)

_ARCHIVE_BYTES_PER_TOKEN_ESTIMATE = 4
_ARCHIVE_RESTORE_BLOCK_PREFIX = "Archive restore blocked."


def _estimate_tokens_from_file_size(byte_count: int) -> int:
    """Estimate restore tokens from bytes without loading archive contents."""
    safe_byte_count = max(byte_count, 0)
    if safe_byte_count == 0:
        return 0
    return max(
        (safe_byte_count + _ARCHIVE_BYTES_PER_TOKEN_ESTIMATE - 1)
        // _ARCHIVE_BYTES_PER_TOKEN_ESTIMATE,
        1,
    )


def format_archive_restore_block(
    decision: ArchiveRefetchDecision,
    *,
    archive_path: str,
    estimated_tokens: int,
) -> str:
    blocked_payload = decision.to_blocked_payload(
        archive_path=archive_path,
        estimated_tokens=estimated_tokens,
    )
    return (
        f"{_ARCHIVE_RESTORE_BLOCK_PREFIX}\n"
        f"{json.dumps(blocked_payload, ensure_ascii=False, sort_keys=True)}"
    )


def parse_archive_restore_block_payload(value: object) -> dict[str, object] | None:
    """Parse the stable blocked-restore payload carried in tool output."""
    if not isinstance(value, str) or not value.startswith(_ARCHIVE_RESTORE_BLOCK_PREFIX):
        return None

    json_start = value.find("{")
    if json_start < 0:
        return None

    try:
        payload = json.loads(value[json_start:])
    except json.JSONDecodeError:
        return None

    if not isinstance(payload, dict) or payload.get("type") != "archive_restore_blocked":
        return None
    return {str(key): item for key, item in payload.items()}


async def evaluate_archive_full_read_before_content(
    *,
    strategy: FileSystemStrategy,
    resolved_path: str,
    view_range: ViewRange | None,
) -> tuple[ArchiveRefetchDecision, int] | None:
    """Block oversized archive full reads before loading file contents."""
    if view_range is not None or not is_context_archive_path(resolved_path):
        return None

    try:
        file_size = await strategy.get_file_size(resolved_path)
    except FileNotFoundError:
        raise
    except Exception:
        logger.warning(
            "Failed to get archive size before read: %s",
            resolved_path,
            exc_info=True,
        )
        return (
            ArchiveRefetchDecision(
                is_archive_path=True,
                allowed=False,
                recorded=False,
                reason="archive_restore_size_probe_failed",
                message=(
                    "Archived context restore blocked because the file size could not be "
                    "validated before reading."
                ),
                suggested_action="Read a narrow line range from the archive instead of the full file.",
                guidance=build_archive_restore_guidance(
                    resolved_path,
                    reason="archive_restore_size_probe_failed",
                    severity="warning",
                ),
            ),
            0,
        )

    estimated_content_tokens = _estimate_tokens_from_file_size(file_size)
    decision = evaluate_archive_refetch_for_path(
        resolved_path,
        estimated_tokens=estimated_content_tokens,
        current_chat_id=get_current_chat_id(),
        is_range_read=False,
        record_allowed=False,
    )
    if decision.is_archive_path and not decision.allowed:
        return decision, estimated_content_tokens
    return None


__all__ = [
    "evaluate_archive_full_read_before_content",
    "format_archive_restore_block",
    "parse_archive_restore_block_payload",
]
