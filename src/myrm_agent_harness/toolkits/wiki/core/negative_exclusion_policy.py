"""Deterministic negative exclusion policy for wiki writeback.

[INPUT]
- candidate text, topic title, metadata tags

[OUTPUT]
- NegativeExclusionReason, ExclusionMatch, evaluate_exclusion_policy

[POS]
Hard boundary guard enforcing the 5 strictly excluded categories from WorkBuddy practice,
preventing ephemeral single-session, mock datasets, client-specific configurations,
and presentation scripts from contaminating the reusable knowledge base.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from re import Pattern


class NegativeExclusionCategory(StrEnum):
    LECTURER_SCRIPT_FULL = "lecturer_script_full"
    DEMO_ENVIRONMENT_SPECIFIC = "demo_environment_specific"
    MOCK_SAMPLE_DATASET = "mock_sample_dataset"
    SINGLE_SESSION_INTERNAL_LOG = "single_session_internal_log"
    ONE_OFF_CLIENT_SPECIFICS = "one_off_client_specifics"


@dataclass(frozen=True, slots=True)
class ExclusionMatch:
    category: NegativeExclusionCategory
    matched_pattern: str
    rationale: str


_PATTERNS: tuple[tuple[NegativeExclusionCategory, Pattern[str], str], ...] = (
    (
        NegativeExclusionCategory.LECTURER_SCRIPT_FULL,
        re.compile(
            r"(逐字稿|主持词|讲师台本|演讲脚本|开场白|欢迎大家来到直播间|请大家看大屏幕)",
            re.IGNORECASE,
        ),
        "单场次演示/讲师逐字稿属于一次性演练素材，严禁回写通用知识库",
    ),
    (
        NegativeExclusionCategory.DEMO_ENVIRONMENT_SPECIFIC,
        re.compile(
            r"(192\.168\.\d+\.\d+|10\.\d+\.\d+\.\d+|172\.(1[6-9]|2\d|3[01])\.\d+\.\d+|localhost:\d{4,5}|internal-vpc|test-env-[a-z0-9]+)",
            re.IGNORECASE,
        ),
        "包含特定局域网测试环境IP、内网VPC或测试端口，禁止回写通用库",
    ),
    (
        NegativeExclusionCategory.MOCK_SAMPLE_DATASET,
        re.compile(
            r"(测试数据表|假数据样本|mock_user|test_client_\d+|张三.*13800000000|身份证测试号码)",
            re.IGNORECASE,
        ),
        "包含一次性虚拟测试数据样本或特定模拟人名，严禁混入真实业务概念",
    ),
    (
        NegativeExclusionCategory.SINGLE_SESSION_INTERNAL_LOG,
        re.compile(
            r"(Traceback \(most recent call last\)|Exception: debug_dump|临时调试堆栈|SessionID: [0-9a-f-]{36})",
            re.IGNORECASE,
        ),
        "包含单次执行的临时崩溃堆栈或内部会话追踪ID，不具备通用知识复利价值",
    ),
    (
        NegativeExclusionCategory.ONE_OFF_CLIENT_SPECIFICS,
        re.compile(
            r"(专属报价单|针对.*公司的特批价格|商务保密折扣|定制SLA违约赔偿条款)",
            re.IGNORECASE,
        ),
        "包含面向特定单一客户的定制商务报价或敏感约束，严禁归档至公开知识库",
    ),
)


def evaluate_exclusion_policy(
    text: str,
    title: str = "",
) -> list[ExclusionMatch]:
    """
    Evaluate candidate text against the 5 negative exclusion categories.
    Returns a list of ExclusionMatch instances. If empty, the text is safe to write back.
    """
    combined = f"{title}\n{text}"
    matches: list[ExclusionMatch] = []
    seen_categories: set[NegativeExclusionCategory] = set()

    for category, pattern, rationale in _PATTERNS:
        if category in seen_categories:
            continue
        found = pattern.search(combined)
        if found:
            matched_str = found.group(0)
            matches.append(
                ExclusionMatch(
                    category=category,
                    matched_pattern=matched_str,
                    rationale=rationale,
                )
            )
            seen_categories.add(category)

    return matches


def is_safe_for_writeback(text: str, title: str = "") -> bool:
    """Convenience helper returning True if text passes all negative exclusion checks."""
    return len(evaluate_exclusion_policy(text, title)) == 0
