"""Unit tests for semantic failure sniffer and observation elevation in tooling middleware.

Tests cover:
1. Exemption filtering (default exempt tools, prefix matches, metadata flags)
2. JSON payload inspection (boolean flags, error status, error codes, nested errors)
3. Error classification (transient/retryable vs permanent/non-retryable)
4. System observation elevation formatting
5. Post-call guard integration with ToolMessage elevation
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import ToolMessage

from myrm_agent_harness.agent.middlewares.tooling._tool_guards import run_post_call_guards
from myrm_agent_harness.agent.middlewares.tooling.semantic_failure_sniffer import (
    SemanticFailureSniffResult,
    SemanticFailureType,
    elevate_semantic_failure_observation,
    should_skip_semantic_sniff,
    sniff_semantic_failure,
)


class TestSemanticFailureSnifferExemptions:
    """Test tool exemption policies."""

    def test_default_exempt_tools(self) -> None:
        assert should_skip_semantic_sniff("bash_code_execute_tool") is True
        assert should_skip_semantic_sniff("file_read_tool") is True
        assert should_skip_semantic_sniff("file_write_tool") is True
        assert should_skip_semantic_sniff("file_edit_tool") is True
        assert should_skip_semantic_sniff("glob_tool") is True
        assert should_skip_semantic_sniff("grep_tool") is True
        assert should_skip_semantic_sniff("diff_tool") is True

    def test_prefix_exemptions(self) -> None:
        assert should_skip_semantic_sniff("test_order_flow") is True
        assert should_skip_semantic_sniff("verify_signature") is True
        assert should_skip_semantic_sniff("check_system_health") is True

    def test_metadata_skip_flag(self) -> None:
        assert should_skip_semantic_sniff("custom_tool", metadata={"skip_semantic_failure_sniffing": True}) is True
        assert should_skip_semantic_sniff("custom_tool", metadata={"skip_semantic_failure_sniffing": False}) is False

    def test_target_mcp_tools_are_not_exempt(self) -> None:
        assert should_skip_semantic_sniff("mcp__github__get_issue") is False
        assert should_skip_semantic_sniff("query_customer_crm") is False


class TestSemanticFailureSnifferInspection:
    """Test payload inspection and error extraction."""

    def test_non_json_strings_ignored(self) -> None:
        res = sniff_semantic_failure("Plain text output without json", tool_name="external_api")
        assert res.is_failure is False
        assert res.failure_type == SemanticFailureType.NONE

    def test_success_payload_not_flagged(self) -> None:
        payload = '{"code": 0, "status": "ok", "data": {"id": "12345"}}'
        res = sniff_semantic_failure(payload, tool_name="order_service")
        assert res.is_failure is False

    def test_explicit_boolean_failure_non_retryable(self) -> None:
        payload = '{"success": false, "message": "User not found", "code": 404}'
        res = sniff_semantic_failure(payload, tool_name="user_service")
        assert res.is_failure is True
        assert res.failure_type == SemanticFailureType.NON_RETRYABLE
        assert res.extracted_code == 404
        assert res.extracted_message == "User not found"

    def test_explicit_boolean_failure_retryable(self) -> None:
        payload = '{"is_success": false, "error": "rate limit exceeded, try again later", "code": 429}'
        res = sniff_semantic_failure(payload, tool_name="llm_service")
        assert res.is_failure is True
        assert res.failure_type == SemanticFailureType.RETRYABLE
        assert res.extracted_code == 429

    def test_status_error_with_nested_payload(self) -> None:
        payload = {
            "status": "error",
            "error": {"code": 403, "message": "Permission denied for tenant resource"},
        }
        res = sniff_semantic_failure(payload, tool_name="tenant_mgr")
        assert res.is_failure is True
        assert res.failure_type == SemanticFailureType.NON_RETRYABLE
        assert res.extracted_code == 403
        assert "Permission denied" in (res.extracted_message or "")

    def test_errors_array_payload(self) -> None:
        payload = {
            "code": 422,
            "errors": [{"field": "email", "reason": "invalid parameter format"}],
        }
        res = sniff_semantic_failure(payload, tool_name="account_api")
        assert res.is_failure is True
        assert res.failure_type == SemanticFailureType.NON_RETRYABLE

    def test_exempt_tool_returns_no_failure(self) -> None:
        payload = '{"status": "error", "code": 500, "message": "fail"}'
        res = sniff_semantic_failure(payload, tool_name="bash_code_execute_tool")
        assert res.is_failure is False


class TestObservationElevation:
    """Test observation elevation text generation."""

    def test_elevation_formatting(self) -> None:
        sniff_result = SemanticFailureSniffResult(
            is_failure=True,
            failure_type=SemanticFailureType.NON_RETRYABLE,
            reason="Explicit failure flag 'success=False'",
            extracted_code=404,
            extracted_message="Resource does not exist",
            raw_payload={"success": False, "code": 404, "message": "Resource does not exist"},
        )
        elevated = elevate_semantic_failure_observation(sniff_result, '{"success": false}')
        assert "[SYSTEM OBSERVATION ELEVATION: TARGET SYSTEM REPORTED BUSINESS FAILURE]" in elevated
        assert "Transport Status: HTTP 200" in elevated
        assert "Business Status: FAILURE" in elevated
        assert "NON-RETRYABLE" in elevated
        assert "Strict Grounding: NEVER hallucinate" in elevated
        assert "Do NOT retry with the identical parameters" in elevated

    def test_retryable_elevation_guidance(self) -> None:
        sniff_result = SemanticFailureSniffResult(
            is_failure=True,
            failure_type=SemanticFailureType.RETRYABLE,
            reason="Non-success code 'code=429'",
            extracted_code=429,
            extracted_message="Too many requests",
            raw_payload={"code": 429, "message": "Too many requests"},
        )
        elevated = elevate_semantic_failure_observation(sniff_result, '{"code": 429}')
        assert "RETRYABLE" in elevated
        assert "This error is transient" in elevated


class TestPostCallGuardsIntegration:
    """Test integration of semantic sniffer inside post-call guards."""

    @pytest.mark.asyncio
    async def test_post_call_elevates_pseudo_success(self) -> None:
        raw_payload = '{"success": false, "code": 404, "message": "Item missing"}'
        initial_msg = ToolMessage(content=raw_payload, name="mcp_query", tool_call_id="call_123")

        mock_loop_guard = MagicMock()
        mock_loop_verdict = MagicMock()
        mock_freq_guard = MagicMock()
        mock_freq_verdict = MagicMock()
        mock_steering_token = MagicMock(has_pending=False)

        with (
            patch(
                "myrm_agent_harness.agent.middlewares.tooling._tool_guards.emit_archive_restore_block_status",
                new_callable=AsyncMock,
            ),
        ):
            elevated_msg = await run_post_call_guards(
                result=initial_msg,
                tool_name="mcp_query",
                tool_call_id="call_123",
                tool_args={"id": "item_1"},
                loop_guard=mock_loop_guard,
                loop_verdict=mock_loop_verdict,
                freq_guard=mock_freq_guard,
                freq_verdict=mock_freq_verdict,
                steering_token=mock_steering_token,
            )

        assert elevated_msg.status == "error"
        assert "[SYSTEM OBSERVATION ELEVATION" in str(elevated_msg.content)
        assert elevated_msg.additional_kwargs.get("error_category") == "non_retryable_business_error"
        assert elevated_msg.additional_kwargs.get("extracted_code") == 404
