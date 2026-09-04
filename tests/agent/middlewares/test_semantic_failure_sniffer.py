"""Unit and integration tests for SemanticFailureSniffer and HTTP 200 observation failure defense.

Covers:
1. Core sniffing logic over various business failure envelopes (success=false, code!=0, errors).
2. Two-tier classification (retryable transient vs non-retryable permanent).
3. False positive prevention (domain entities with status="failed", valid data, etc.).
4. Tool exemptions and metadata-based bypass switches.
5. Observation elevation formatting and anti-hallucination guidance for LLMs.
6. Integration with run_post_call_guards flipping ToolMessage status to error.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import ToolMessage

from myrm_agent_harness.agent.middlewares.tooling._tool_guards import (
    run_post_call_guards,
)
from myrm_agent_harness.agent.middlewares.tooling.semantic_failure_sniffer import (
    SemanticFailureSniffResult,
    SemanticFailureType,
    elevate_semantic_failure_observation,
    should_skip_semantic_sniff,
    sniff_semantic_failure,
)
from myrm_agent_harness.agent.security.guards.loop_guard import LoopGuard, LoopVerdict


class TestSemanticFailureSnifferCore:
    """Tests for pure payload sniffing logic."""

    def test_explicit_success_false_payload(self) -> None:
        payload = {"success": False, "error": "订单不存在", "code": 404}
        res = sniff_semantic_failure(payload, tool_name="order_query_tool")

        assert res.is_failure is True
        assert res.failure_type == SemanticFailureType.NON_RETRYABLE
        assert res.extracted_code == 404
        assert res.extracted_message == "订单不存在"
        assert "Explicit failure flag" in res.reason

    def test_wechat_style_errcode_payload(self) -> None:
        payload = '{"errcode": 40001, "errmsg": "invalid credential, access_token is invalid"}'
        res = sniff_semantic_failure(payload, tool_name="mcp_wechat_send")

        assert res.is_failure is True
        assert res.failure_type == SemanticFailureType.NON_RETRYABLE
        assert res.extracted_code == 40001
        assert res.extracted_message == "invalid credential, access_token is invalid"

    def test_retryable_rate_limit_payload(self) -> None:
        payload = {"code": 429, "message": "Too Many Requests: rate limit exceeded"}
        res = sniff_semantic_failure(payload, tool_name="crm_api_tool")

        assert res.is_failure is True
        assert res.failure_type == SemanticFailureType.RETRYABLE
        assert res.extracted_code == 429

    def test_retryable_concurrency_conflict_chinese(self) -> None:
        payload = {"status": "error", "msg": "系统繁忙，存在并发锁冲突，请稍后重试"}
        res = sniff_semantic_failure(payload, tool_name="inventory_deduct_tool")

        assert res.is_failure is True
        assert res.failure_type == SemanticFailureType.RETRYABLE
        assert "Explicit status" in res.reason

    def test_root_error_string_payload(self) -> None:
        payload = {"error": "unauthorized access to resource"}
        res = sniff_semantic_failure(payload, tool_name="vault_secret_tool")

        assert res.is_failure is True
        assert res.failure_type == SemanticFailureType.NON_RETRYABLE
        assert res.extracted_message == "unauthorized access to resource"

    def test_errors_array_payload(self) -> None:
        payload = {"errors": [{"message": "Field 'email' is invalid"}]}
        res = sniff_semantic_failure(payload, tool_name="user_create_tool")

        assert res.is_failure is True
        assert res.failure_type == SemanticFailureType.NON_RETRYABLE
        assert res.extracted_message == "Field 'email' is invalid"


class TestSemanticFailureFalsePositiveDefense:
    """Tests ensuring valid business outputs are not misclassified as errors."""

    def test_valid_successful_payload(self) -> None:
        payload = {"success": True, "code": 0, "data": {"id": "ord_1001", "amount": 99.5}}
        res = sniff_semantic_failure(payload, tool_name="order_query_tool")

        assert res.is_failure is False
        assert res.failure_type == SemanticFailureType.NONE

    def test_normal_json_string_success(self) -> None:
        payload = json.dumps({"status": "success", "result": [1, 2, 3]})
        res = sniff_semantic_failure(payload, tool_name="batch_calc_tool")

        assert res.is_failure is False

    def test_domain_entity_state_not_rpc_failure(self) -> None:
        # Querying a build job whose own status happened to be 'failed'
        payload = {
            "task_id": "ci_build_982",
            "status": "failed",
            "exit_code": 1,
            "duration": 42.5,
        }
        res = sniff_semantic_failure(payload, tool_name="get_build_status")

        assert res.is_failure is False

    def test_entity_with_substantive_data_and_failed_field(self) -> None:
        payload = {
            "order_id": "OD_7788",
            "payment_status": "failed",
            "items": [{"name": "Widget A", "qty": 2}],
        }
        res = sniff_semantic_failure(payload, tool_name="order_detail_tool")

        assert res.is_failure is False

    def test_plain_text_not_json_object(self) -> None:
        plain_text = "Task finished with status: failed on worker 3"
        res = sniff_semantic_failure(plain_text, tool_name="custom_tool")

        assert res.is_failure is False


class TestToolExemptionsAndMetadata:
    """Tests for bypass rules."""

    def test_default_exempt_tool_names(self) -> None:
        payload = {"error": "syntax error", "code": 1}
        assert should_skip_semantic_sniff("bash_code_execute_tool") is True
        assert should_skip_semantic_sniff("file_read_tool") is True
        assert should_skip_semantic_sniff("web_search") is True

        res = sniff_semantic_failure(payload, tool_name="bash_code_execute_tool")
        assert res.is_failure is False
        assert "exempt" in res.reason

    def test_prefix_exempt_tool_names(self) -> None:
        assert should_skip_semantic_sniff("memory_retrieve") is True
        assert should_skip_semantic_sniff("knowledge_search") is True
        assert should_skip_semantic_sniff("test_runner") is True
        assert should_skip_semantic_sniff("browser_click") is True

    def test_metadata_skip_override(self) -> None:
        payload = {"success": False, "error": "Expected business denial in test"}
        res = sniff_semantic_failure(
            payload,
            tool_name="some_mcp_tool",
            tool_metadata={"skip_semantic_failure_sniffing": True},
        )
        assert res.is_failure is False
        assert "exempt" in res.reason


class TestObservationElevation:
    """Tests for formatting elevated LLM observations."""

    def test_elevation_content_and_rules(self) -> None:
        sniff_result = SemanticFailureSniffResult(
            is_failure=True,
            failure_type=SemanticFailureType.NON_RETRYABLE,
            reason="Explicit failure flag 'success=False'",
            extracted_code=404,
            extracted_message="订单不存在",
            raw_payload={"success": False, "error": "订单不存在"},
        )
        elevated = elevate_semantic_failure_observation(sniff_result, '{"success": false}')

        assert "[SYSTEM OBSERVATION ELEVATION: TARGET SYSTEM REPORTED BUSINESS FAILURE]" in elevated
        assert "Transport Status: HTTP 200 / Communication Succeeded" in elevated
        assert "Business Status: FAILURE (Explicit failure flag 'success=False') [Code: 404] [Message: 订单不存在]" in elevated
        assert "NON-RETRYABLE (permanent business failure)" in elevated
        assert "Strict Grounding: NEVER hallucinate that the record exists" in elevated
        assert "Do NOT retry with the identical parameters" in elevated

    def test_retryable_action_guidance(self) -> None:
        sniff_result = SemanticFailureSniffResult(
            is_failure=True,
            failure_type=SemanticFailureType.RETRYABLE,
            reason="Rate limited",
            extracted_code=429,
            extracted_message="Too many requests",
            raw_payload={"code": 429},
        )
        elevated = elevate_semantic_failure_observation(sniff_result, "{}")

        assert "RETRYABLE (transient system state)" in elevated
        assert "Action Guidance: This error is transient" in elevated
        assert "retry after a backoff" in elevated


class TestPostCallGuardsIntegration:
    """Integration test verifying run_post_call_guards flips ToolMessage to error."""

    @pytest.mark.asyncio
    async def test_post_call_guards_flips_pseudo_success_tool_message(self) -> None:
        initial_msg = ToolMessage(
            content='{"success": false, "error": "客户信息不存在", "code": 404}',
            name="customer_mcp_query",
            tool_call_id="call_abc_123",
            status="success",
        )

        mock_loop_guard = MagicMock(spec=LoopGuard)
        mock_loop_verdict = MagicMock(spec=LoopVerdict)
        mock_loop_verdict.action.value = "allow"
        mock_freq_guard = MagicMock()
        mock_freq_verdict = MagicMock()

        with patch("myrm_agent_harness.agent.security.audit.record_decision"):
            result_msg = await run_post_call_guards(
                result=initial_msg,
                tool_name="customer_mcp_query",
                tool_call_id="call_abc_123",
                tool_args={"customer_id": "C999"},
                loop_guard=mock_loop_guard,
                loop_verdict=mock_loop_verdict,
                freq_guard=mock_freq_guard,
                freq_verdict=mock_freq_verdict,
                steering_token=None,
            )

        assert isinstance(result_msg, ToolMessage)
        assert result_msg.status == "error"
        assert "[SYSTEM OBSERVATION ELEVATION: TARGET SYSTEM REPORTED BUSINESS FAILURE]" in str(result_msg.content)
        assert result_msg.additional_kwargs.get("error_category") == "non_retryable_business_error"
        assert result_msg.additional_kwargs.get("extracted_code") == 404
        assert "Explicit failure flag" in str(result_msg.additional_kwargs.get("semantic_failure_reason"))

    @pytest.mark.asyncio
    async def test_post_call_guards_leaves_normal_output_untouched(self) -> None:
        initial_msg = ToolMessage(
            content='{"success": true, "data": {"name": "Alice"}}',
            name="customer_mcp_query",
            tool_call_id="call_abc_456",
            status="success",
        )

        mock_loop_guard = MagicMock(spec=LoopGuard)
        mock_loop_verdict = MagicMock(spec=LoopVerdict)
        mock_loop_verdict.action.value = "allow"
        mock_freq_guard = MagicMock()
        mock_freq_verdict = MagicMock()

        with patch("myrm_agent_harness.agent.security.audit.record_decision"):
            result_msg = await run_post_call_guards(
                result=initial_msg,
                tool_name="customer_mcp_query",
                tool_call_id="call_abc_456",
                tool_args={"customer_id": "C100"},
                loop_guard=mock_loop_guard,
                loop_verdict=mock_loop_verdict,
                freq_guard=mock_freq_guard,
                freq_verdict=mock_freq_verdict,
                steering_token=None,
            )

        assert isinstance(result_msg, ToolMessage)
        assert result_msg.status == "success"
        assert '{"success": true, "data": {"name": "Alice"}}' in str(result_msg.content)
