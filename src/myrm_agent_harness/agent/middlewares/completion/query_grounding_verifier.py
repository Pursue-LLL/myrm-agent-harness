"""Query grounding verifier for CompletionGuard.

Detects business entity state/data query intents (orders, tickets, transactions,
accounts, logistics) and enforces physical evidence collection. Blocks completion
when the agent hallucinates data without executing query tools, or fabricates
success claims when all query tools failed.

Complements external_evidence (which covers web freshness and citations) by
safeguarding everyday enterprise entity queries.

[INPUT]
- User request text (extracted from latest HumanMessage)
- Assistant final text (AIMessage content)
- Session CallRecord window (LoopGuard)

[OUTPUT]
- check_query_grounding_claim(): reason string when blocking is required, else None
- detect_entity_query_intent(): bool
- has_successful_query_evidence(): bool

[POS]
Harness middleware helper; invoked from CompletionGuard.aafter_model at completion.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from myrm_agent_harness.agent.security.guards.loop_guard import SuccessLevel
from myrm_agent_harness.toolkits.mcp.config import is_mcp_tool_name

if TYPE_CHECKING:
    from myrm_agent_harness.agent.security.guards.loop_guard import CallRecord

_MCP_PTC_BASH_MARKER = "skills.mcp_"

# 概念性/教学/架构/规范等说明文意图排除：避免"如何设计订单系统"被误判为查单
_EXPLANATION_EXCLUSIONS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)(什么是|如何设计|如何实现|怎么实现|怎么设计|怎么写|原理|架构|定义|规范|最佳实践)"),
    re.compile(r"(?i)\b(what is|how to design|how to implement|how does|architecture of|best practices? for)\b"),
)

# 中文实体查询动宾意图正则
_ZH_QUERY_VERBS = r"(查|查询|查看|查下|检索|获取|核对|查阅|调取|看下|看看)"
_ZH_ENTITY_NOUNS = (
    r"(订单|工单|流水|发票|报销|运单|物流|快递|账户|余额|客户|合同|账单|明细|处理进度|审批状态|物流信息|轨迹)"
)
_ZH_INTENT_PATTERN = re.compile(rf"{_ZH_QUERY_VERBS}.*{_ZH_ENTITY_NOUNS}|{_ZH_ENTITY_NOUNS}.*{_ZH_QUERY_VERBS}")

# 英文实体查询动宾意图正则
_EN_INTENT_PATTERN = re.compile(
    r"(?i)\b(check|query|lookup|look up|search for|get|fetch|retrieve|track|find)\b.*"
    r"\b(order|ticket|invoice|transaction|tracking|shipment|logistics|account|balance|customer|contract|receipt|approval)\b"
)

# 显式单号标识符模式（如 OD-12345, ORDER_9921, TK-8802）配合查询动词
_IDENTIFIER_PATTERN = re.compile(
    r"(?i)\b([A-Z]{2,8}[-_]\d{3,20}|(?:order|ticket|invoice|txn|bill)[-_#]?\d{3,20})\b"
)

# 诚实否定与澄清模式：模型若如实声明查不到、不存在或请求澄清，合法放行，严禁误阻断
_HONEST_NEGATIVE_OR_CLARIFICATION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"(未找到|不存在|没有找到|暂无|查无|未查询到|未能查询到|查询失败|接口报错|系统异常|无此记录|找不到|未检索到|请提供|无法获取|暂未查到)"
    ),
    re.compile(
        r"(?i)\b(not found|does not exist|no record|no order|no ticket|failed to query|unable to retrieve|could not find|please provide|cannot find)\b"
    ),
)

_KNOWN_QUERY_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "web_search_tool",
        "web_fetch_tool",
        "browser_navigate_tool",
        "browser_extract_tool",
        "browser_snapshot_tool",
        "browser_inspect_tool",
        "sql_query_tool",
        "database_query_tool",
    }
)

_QUERY_TOOL_NAME_SUBSTRINGS: tuple[str, ...] = (
    "search",
    "query",
    "lookup",
    "fetch",
    "get_",
    "read_",
    "find_",
    "list_",
    "check_",
)


def detect_entity_query_intent(user_text: str | None) -> bool:
    """Return True when user text indicates an intent to query a specific business entity."""
    if not user_text:
        return False
    text = user_text.strip()
    if not text:
        return False

    # 1. 排除教学、概念、架构等说明文问法
    for pattern in _EXPLANATION_EXCLUSIONS:
        if pattern.search(text):
            return False

    # 2. 动宾查询匹配
    if _ZH_INTENT_PATTERN.search(text):
        return True
    if _EN_INTENT_PATTERN.search(text):
        return True

    # 3. 显式实体编号（如 OD-9921）且伴随查询动词
    if _IDENTIFIER_PATTERN.search(text):
        zh_verbs = ("查", "看", "找", "确认")
        en_verbs = ("check", "find", "get", "status", "query", "look")
        lowered = text.lower()
        if any(v in text for v in zh_verbs) or any(v in lowered for v in en_verbs):
            return True

    return False


def is_honest_negative_or_clarification(content: str | None) -> bool:
    """Return True if assistant response honestly reports missing data or asks for clarification."""
    if not content:
        return False
    text = content.strip()
    if not text:
        return False

    return any(p.search(text) is not None for p in _HONEST_NEGATIVE_OR_CLARIFICATION_PATTERNS)


def _is_query_tool_name(tool_name: str) -> bool:
    if not tool_name or tool_name.startswith("_"):
        return False
    if is_mcp_tool_name(tool_name) or tool_name in _KNOWN_QUERY_TOOL_NAMES:
        return True
    lowered = tool_name.lower()
    return any(sub in lowered for sub in _QUERY_TOOL_NAME_SUBSTRINGS)


def _is_bash_ptc_query(record: CallRecord) -> bool:
    if record.tool_name != "bash_code_execute_tool":
        return False
    args = getattr(record, "args", None)
    if not isinstance(args, dict):
        return False
    cmd = args.get("command")
    if not isinstance(cmd, str):
        return False
    return _MCP_PTC_BASH_MARKER in cmd


def is_query_call_record(record: CallRecord) -> bool:
    """True when record corresponds to a query, MCP, or search tool call."""
    if _is_query_tool_name(record.tool_name):
        return True
    return _is_bash_ptc_query(record)


def has_successful_query_evidence(records: list[CallRecord]) -> bool:
    """Return True if at least one query tool completed without FAILURE."""
    for record in records:
        if not is_query_call_record(record):
            continue
        success_level = getattr(record, "success_level", None)
        if success_level is None or success_level == SuccessLevel.FAILURE:
            continue
        return True
    return False


def check_query_grounding_claim(
    user_text: str | None,
    assistant_text: str | None,
    records: list[CallRecord],
) -> str | None:
    """Evaluate whether an entity query request has verified physical evidence.

    Returns a blocking reason if the agent claims success or fabricates data without
    successful query tool execution, or None if acceptable.
    """
    if not detect_entity_query_intent(user_text):
        return None

    # 模型诚实告知查无此单或接口报错，属于合规诚实回答，不予阻断
    if is_honest_negative_or_clarification(assistant_text):
        return None

    # 如果有至少一次成功的查询记录，放行
    if has_successful_query_evidence(records):
        return None

    # 收集本次会话中所有相关的查询工具记录
    query_records = [r for r in records if is_query_call_record(r)]

    if not query_records:
        return (
            "The user requested querying a specific business entity (order, ticket, transaction, "
            "account, or logistics), but no query or MCP tool was executed. "
            "Execute the appropriate query tool to retrieve real data before answering, "
            "or honestly state to the user if the information is unavailable."
        )

    return (
        "The user requested querying a business entity, but all related tool executions failed. "
        "Do not fabricate hypothetical query results or claim successful retrieval. "
        "Honestly report the tool failure details or missing status to the user, "
        "or ask for necessary clarification."
    )


__all__ = [
    "check_query_grounding_claim",
    "detect_entity_query_intent",
    "has_successful_query_evidence",
    "is_honest_negative_or_clarification",
    "is_query_call_record",
]
