"""Unit tests for CompletionGuard query grounding verifier."""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from myrm_agent_harness.agent.middlewares.completion.completion_guard import (
    CompletionGuard,
    reset_completion_guard,
)
from myrm_agent_harness.agent.middlewares.completion.query_grounding_verifier import (
    check_query_grounding_claim,
    detect_entity_query_intent,
    has_successful_query_evidence,
    is_honest_negative_or_clarification,
    is_query_call_record,
)
from myrm_agent_harness.agent.middlewares.tooling.tool_interceptor_middleware import (
    reset_loop_guard,
)
from myrm_agent_harness.agent.security.guards.loop_guard.types import (
    CallRecord,
    SuccessLevel,
)


def _record(
    tool_name: str,
    level: SuccessLevel = SuccessLevel.FULL_SUCCESS,
    args: dict[str, object] | None = None,
) -> CallRecord:
    return CallRecord(
        tool_name=tool_name,
        args_hash="hash_1",
        args=args or {},
        success_level=level,
    )


class TestDetectEntityQueryIntent:
    def test_empty_input_returns_false(self) -> None:
        assert detect_entity_query_intent("") is False
        assert detect_entity_query_intent(None) is False
        assert detect_entity_query_intent("   ") is False

    def test_chinese_entity_queries(self) -> None:
        assert detect_entity_query_intent("帮我查一下订单状态") is True
        assert detect_entity_query_intent("查询工单处理进度") is True
        assert detect_entity_query_intent("查看客户张三的账户余额") is True
        assert detect_entity_query_intent("核对昨天的交易流水明细") is True
        assert detect_entity_query_intent("看一下发票报销审批状态") is True
        assert detect_entity_query_intent("获取快递物流轨迹") is True

    def test_english_entity_queries(self) -> None:
        assert detect_entity_query_intent("check the status of order 12345") is True
        assert detect_entity_query_intent("lookup ticket TK-9901") is True
        assert detect_entity_query_intent("fetch invoice details for account") is True
        assert detect_entity_query_intent("retrieve transaction history") is True
        assert detect_entity_query_intent("track shipment progress") is True

    def test_explicit_identifier_pattern(self) -> None:
        assert detect_entity_query_intent("查一下 OD-99218") is True
        assert detect_entity_query_intent("check TK-8802 status") is True
        assert detect_entity_query_intent("查看 order-100234") is True

    def test_explanation_and_design_exclusions(self) -> None:
        assert detect_entity_query_intent("什么是订单系统？") is False
        assert detect_entity_query_intent("如何设计一个高并发工单流水架构") is False
        assert detect_entity_query_intent("怎么实现发票核销的数据库表结构") is False
        assert detect_entity_query_intent("what is the architecture of an order service") is False
        assert detect_entity_query_intent("how to design ticket workflow") is False

    def test_casual_and_coding_prompts_pass(self) -> None:
        assert detect_entity_query_intent("你好，请介绍一下你自己") is False
        assert detect_entity_query_intent("写一个快速排序算法") is False
        assert detect_entity_query_intent("帮我重构一下 utils.py 中的函数") is False


class TestIsHonestNegativeOrClarification:
    def test_empty_returns_false(self) -> None:
        assert is_honest_negative_or_clarification("") is False
        assert is_honest_negative_or_clarification(None) is False

    def test_honest_chinese_negatives(self) -> None:
        assert is_honest_negative_or_clarification("抱歉，系统中未找到该订单的信息。") is True
        assert is_honest_negative_or_clarification("该工单不存在或已被删除。") is True
        assert is_honest_negative_or_clarification("查询接口报错，系统异常无法获取流水。") is True
        assert is_honest_negative_or_clarification("暂无此记录，请提供正确的订单编号。") is True

    def test_honest_english_negatives(self) -> None:
        assert is_honest_negative_or_clarification("Order OD-123 was not found in the database.") is True
        assert is_honest_negative_or_clarification("The ticket does not exist.") is True
        assert is_honest_negative_or_clarification("Failed to query the transaction records.") is True
        assert is_honest_negative_or_clarification("Please provide a valid ticket ID.") is True

    def test_affirmative_claims_return_false(self) -> None:
        assert is_honest_negative_or_clarification("您的订单已发货，快递单号为 SF123456。") is False
        assert is_honest_negative_or_clarification("工单已经审批完成，账户余额为 1000 元。") is False


class TestQueryCallRecords:
    def test_is_query_call_record(self) -> None:
        assert is_query_call_record(_record("mcp__crm__get_order")) is True
        assert is_query_call_record(_record("web_search_tool")) is True
        assert is_query_call_record(_record("sql_query_tool")) is True
        assert is_query_call_record(_record("query_database")) is True
        assert is_query_call_record(
            _record("bash_code_execute_tool", args={"command": "python -c 'import skills.mcp_order'"})
        ) is True
        assert is_query_call_record(_record("file_write_tool")) is False
        assert is_query_call_record(_record("_completion_check")) is False

    def test_has_successful_query_evidence(self) -> None:
        assert has_successful_query_evidence([]) is False
        # Failed query does not count
        failed_rec = _record("mcp__crm__get_order", SuccessLevel.FAILURE)
        assert has_successful_query_evidence([failed_rec]) is False

        # Successful query counts
        success_rec = _record("mcp__crm__get_order", SuccessLevel.FULL_SUCCESS)
        assert has_successful_query_evidence([failed_rec, success_rec]) is True


class TestCheckQueryGroundingClaim:
    def test_no_query_intent_returns_none(self) -> None:
        assert (
            check_query_grounding_claim(
                user_text="请帮我写一段冒泡排序代码",
                assistant_text="这是冒泡排序的实现...",
                records=[],
            )
            is None
        )

    def test_query_intent_with_honest_negative_returns_none(self) -> None:
        assert (
            check_query_grounding_claim(
                user_text="查一下订单 OD-9921",
                assistant_text="抱歉，在系统中未找到订单 OD-9921 的任何记录。",
                records=[],
            )
            is None
        )

    def test_query_intent_with_successful_evidence_returns_none(self) -> None:
        records = [
            _record(
                "mcp__erp__query_order",
                SuccessLevel.FULL_SUCCESS,
                args={"order_id": "OD-9921"},
            )
        ]
        assert (
            check_query_grounding_claim(
                user_text="查一下订单 OD-9921 的状态",
                assistant_text="订单 OD-9921 当前状态为已发货。",
                records=records,
            )
            is None
        )

    def test_generic_query_intent_without_id_passes_with_any_query_tool(self) -> None:
        records = [_record("mcp__erp__query_order", SuccessLevel.FULL_SUCCESS)]
        assert (
            check_query_grounding_claim(
                user_text="帮我查询一下订单发货处理进度",
                assistant_text="当前订单均处于正常处理中。",
                records=records,
            )
            is None
        )

    def test_multi_entity_query_missing_one_blocks(self) -> None:
        # 用户查了两个单号：OD-9921 和 TK-8802；工具只查了 OD-9921
        records = [
            _record(
                "mcp__erp__query_order",
                SuccessLevel.FULL_SUCCESS,
                args={"order_id": "OD-9921"},
            )
        ]
        reason = check_query_grounding_claim(
            user_text="帮我查一下订单 OD-9921 的状态，顺便看一下工单 TK-8802 的进度",
            assistant_text="订单 OD-9921 已发货，工单 TK-8802 已由技术人员处理完毕。",
            records=records,
        )
        assert reason is not None
        assert "multiple business entities" in reason
        assert "TK-8802" in reason

    def test_multi_entity_query_missing_one_with_honest_negative_passes(self) -> None:
        # 用户查了两个单号；工具只查了 OD-9921，但在回答中如实说明 TK-8802 未查询到
        records = [
            _record(
                "mcp__erp__query_order",
                SuccessLevel.FULL_SUCCESS,
                args={"order_id": "OD-9921"},
            )
        ]
        assert (
            check_query_grounding_claim(
                user_text="帮我查一下订单 OD-9921 的状态，顺便看一下工单 TK-8802 的进度",
                assistant_text="订单 OD-9921 已经发货；工单 TK-8802 暂未查询到对应处理进度。",
                records=records,
            )
            is None
        )

    def test_multi_entity_query_all_grounded_passes(self) -> None:
        # 用户查了两个单号，两个单号在不同的工具调用入参中均有物理证据
        records = [
            _record(
                "mcp__erp__query_order",
                SuccessLevel.FULL_SUCCESS,
                args={"order_id": "OD-9921"},
            ),
            _record(
                "mcp__itsm__query_ticket",
                SuccessLevel.FULL_SUCCESS,
                args={"ticket_id": "TK-8802"},
            ),
        ]
        assert (
            check_query_grounding_claim(
                user_text="帮我查一下订单 OD-9921 的状态，顺便看一下工单 TK-8802 的进度",
                assistant_text="订单 OD-9921 已发货，工单 TK-8802 处理中。",
                records=records,
            )
            is None
        )

    def test_query_intent_with_zero_tool_calls_blocks(self) -> None:
        reason = check_query_grounding_claim(
            user_text="查一下订单 OD-9921 的状态",
            assistant_text="订单 OD-9921 当前状态为已发货，预计明天送达。",
            records=[],
        )
        assert reason is not None
        assert "no query or MCP tool was executed" in reason

    def test_query_intent_with_all_failed_tools_blocks(self) -> None:
        records = [
            _record("mcp__erp__query_order", SuccessLevel.FAILURE),
            _record("sql_query_tool", SuccessLevel.FAILURE),
        ]
        reason = check_query_grounding_claim(
            user_text="查一下订单 OD-9921 的状态",
            assistant_text="订单 OD-9921 已经顺利出库发货。",
            records=records,
        )
        assert reason is not None
        assert "all related tool executions failed" in reason


@pytest.mark.asyncio
async def test_completion_guard_blocks_ungrounded_entity_query() -> None:
    reset_completion_guard()
    reset_loop_guard()

    guard = CompletionGuard(enabled=True)
    messages = [
        HumanMessage(content="帮我查一下工单 TK-998 的处理进度"),
        AIMessage(content="工单 TK-998 已经由运维团队处理完毕。"),
    ]
    state = {"messages": messages}
    result = await guard.aafter_model(state, runtime={})

    assert result is not None
    assert "messages" in result
    patched_msg = result["messages"][0]
    assert isinstance(patched_msg, AIMessage)
    assert len(patched_msg.tool_calls) == 1
    tc = patched_msg.tool_calls[0]
    assert tc["name"] == "_completion_check"
    assert "query_grounding_reason" in tc["args"]
    assert "no query or MCP tool was executed" in str(tc["args"]["query_grounding_reason"])
