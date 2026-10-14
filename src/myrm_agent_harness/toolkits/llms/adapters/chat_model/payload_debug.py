"""Opt-in diagnostics for failed LLM requests.

[INPUT]
- none

[OUTPUT]
- dump_payload_pairing: log the tool_call / tool-result pairing health of a failed request payload

[POS]
Failure-path debug aid for the generation mixins. The caller gates it behind MYRM_DEBUG_DUMP_LLM_PAYLOAD=1
so production traces stay clean.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def dump_payload_pairing(message_dicts: list[dict[str, Any]]) -> None:
    """Debug aid: log tool_call pairing health for a failed request payload.

    Gated behind MYRM_DEBUG_DUMP_LLM_PAYLOAD=1 so production traces stay clean.
    """
    pending: list[tuple[int, str]] = []
    for i, m in enumerate(message_dicts):
        role = m.get("role")
        if role == "assistant":
            for tc in m.get("tool_calls") or []:
                if not isinstance(tc, dict):
                    continue
                tid = tc.get("id")
                fn = tc.get("function")
                if not tid and isinstance(fn, dict):
                    tid = fn.get("id")
                if tid:
                    pending.append((i, tid))
        elif role == "tool":
            tid = m.get("tool_call_id")
            if tid:
                pending = [(idx, p) for idx, p in pending if p != tid]

    def _tc_ids(m: dict[str, Any]) -> list[object]:
        raw = m.get("tool_calls") or []
        return [tc.get("id") for tc in raw if isinstance(tc, dict)]

    lines = [
        f"  [{i}] role={m.get('role')} tool_call_id={m.get('tool_call_id')!r} "
        f"tool_calls={_tc_ids(m)} content={(str(m.get('content'))[:70])!r}"
        for i, m in enumerate(message_dicts)
    ]
    logger.error(
        " LLM_PAYLOAD_DUMP total=%d dangling=%s (last 35 msgs):\n%s",
        len(message_dicts),
        pending,
        "\n".join(lines[-35:]),
    )
