"""Transient business facts vs memory write boundary helpers.

Hard guard for memory_save when content looks like a dynamic business transient state
(orders, packages/logistics, realtime balances, OTP/auth codes, ephemeral links/queues),
and shared heuristics for auto-extraction filters.

[INPUT]
- (none — pure heuristics and counters)

[OUTPUT]
- looks_like_transient_business_fact: Heuristic for transient business state memory payloads.
- transient_fact_save_rejection_message: Rejection message guiding tool to query live API / session.
- filter_transient_business_memories: Drop transient business semantic/episodic memories before persist.
- record_transient_fact_rejection / get_transient_fact_rejection_count: Guard metrics.

[POS]
Transient business fact memory write boundary heuristics. Keeps real-time business states out of long-term L3 memory.
"""

from __future__ import annotations

import logging
import re
import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.memory.types import AnyMemory

logger = logging.getLogger(__name__)

# Precompiled bilingual patterns for high-precision transient business facts detection
_LOGISTICS_ORDER_PATTERNS = (
    re.compile(
        r"(?:(?:order|package|delivery|parcel|tracking|shipment|courier)\b.*)"
        r"(?:out for delivery|in transit|shipped|dispatched|sorting hub|customs clearance|awaiting pickup|delivered to locker)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:(?:快递|包裹|订单|运单|物流|快件).*)"
        r"(?:正在派送|已出库|运输中|分拨中心|派件中|已揽收|到达|自提柜|已发货|配送中|分拣中)",
    ),
)

_FINANCIAL_BALANCE_PATTERNS = (
    re.compile(
        r"(?:(?:current|available|live|wallet|account|credit|card)\s+(?:balance|credit|limit|funds)).*"
        r"(?:is|are|of|remaining|amounting to|:)?\s*[\$¥€£]?\s*\d+",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:(?:当前|账户|钱包|信用卡|可用|活期|实时)(?:余额|额度|资金|可用金)).*"
        r"(?:为|是|剩余|共计|：|:|\s)\s*[¥\$]?\s*\d+",
    ),
)

_AUTH_OTP_PATTERNS = (
    re.compile(
        r"(?:(?:verification|security|auth(?:entication)?|one-time|login|sms)\s*(?:code|pin|otp|token|password))\s*"
        r"(?:is|:|=|\s)\s*[a-zA-Z0-9]{4,8}\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:(?:(?:短信|登录|动态|安全|身份|一次性)?(?:验证码|动态码|授权码|密码|口令)))[\s:：为是]*[a-zA-Z0-9]{4,8}\b",
    ),
)

_EPHEMERAL_LINK_QUEUE_PATTERNS = (
    re.compile(
        r"(?:presigned[\s_-]?url|temp(?:orary)?[\s_-]?(?:link|url|download)|download[\s_-]?(?:token|link)|auth[\s_-]?token|queue[\s_-]?(?:position|number|status)).*"
        r"(?:expires in|valid for|\b\d+\s*(?:mins?|minutes?|seconds?|hours?)\b)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:临时(?:链接|下载地址|访问令牌)|签名\s*(?:url|链接|地址)|排队(?:序号|位置|进度)).*"
        r"(?:有效(?:期|时间)|过期|还剩|当前第|\d+\s*(?:秒|分|小时))",
        re.IGNORECASE,
    ),
)

_ALL_TRANSIENT_PATTERNS = (
    *_LOGISTICS_ORDER_PATTERNS,
    *_FINANCIAL_BALANCE_PATTERNS,
    *_AUTH_OTP_PATTERNS,
    *_EPHEMERAL_LINK_QUEUE_PATTERNS,
)

_rejection_lock = threading.Lock()
_transient_fact_save_rejections = 0


def looks_like_transient_business_fact(content: str) -> bool:
    """Return True when content represents a real-time transient business state rather than durable memory."""
    stripped = content.strip()
    if not stripped:
        return False
    return any(pattern.search(stripped) for pattern in _ALL_TRANSIENT_PATTERNS)


def transient_fact_save_rejection_message() -> str:
    """Rejection message for transient business state memory payloads."""
    return (
        "Rejected: content represents a real-time transient business state (such as order status, logistics, "
        "live balances, OTP/verification codes, or temporary queue links). Real-time business data must be queried "
        "via live tools/APIs or stored in session memory (MemorySession), never persisted into long-term L3 memory. "
        "Memory is strictly for durable facts, user preferences, and stable behavioral rules."
    )


def record_transient_fact_rejection() -> int:
    """Increment rejection counter and return the new total."""
    global _transient_fact_save_rejections
    with _rejection_lock:
        _transient_fact_save_rejections += 1
        total = _transient_fact_save_rejections
    logger.info("transient_fact_save_rejected total=%d", total)
    return total


def get_transient_fact_rejection_count() -> int:
    """Return current count of transient fact rejections."""
    with _rejection_lock:
        return _transient_fact_save_rejections


def reset_transient_fact_rejection_count() -> None:
    """Reset the rejection counter to zero (for testing)."""
    global _transient_fact_save_rejections
    with _rejection_lock:
        _transient_fact_save_rejections = 0


def filter_transient_business_memories(
    memories: list[AnyMemory],
) -> tuple[list[AnyMemory], int]:
    """Drop transient business state memories before persist.

    Only filters SemanticMemory and EpisodicMemory; ProfileEntry (preferences/identity)
    and ProceduralMemory (rules) are preserved.
    """
    from myrm_agent_harness.toolkits.memory.types import EpisodicMemory, SemanticMemory

    if not memories:
        return memories, 0

    kept: list[AnyMemory] = []
    dropped = 0
    for m in memories:
        if isinstance(m, (SemanticMemory, EpisodicMemory)) and looks_like_transient_business_fact(m.content):
            dropped += 1
            logger.info("Dropped transient business memory: %s", m.content[:80])
        else:
            kept.append(m)

    return kept, dropped
