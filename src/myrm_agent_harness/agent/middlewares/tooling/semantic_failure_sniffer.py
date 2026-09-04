"""MCP and external tool observation semantic failure sniffer and two-tier error classifier.

Detects HTTP 200 pseudo-success responses where transport succeeded but target
service returned a business failure payload (e.g. {"success": false}, {"code": 404}).
Elevates silent business failures into explicit structured warnings and classifies
them into retryable vs non-retryable tiers to prevent agent hallucination loops.

[INPUT]
- core.security.detection.content_boundary::extract_wrapped_payload (POS: Unwrap security boundary markers)

[OUTPUT]
- SemanticFailureType: Enum for failure classification (NONE, RETRYABLE, NON_RETRYABLE)
- SemanticFailureSniffResult: Data class containing detection outcome and extracted metadata
- should_skip_semantic_sniff: Check if tool is exempt from sniffing
- sniff_semantic_failure: Pure function analyzing observation payloads for business failures
- elevate_semantic_failure_observation: Format elevated error warning for LLM grounding

[POS]
Tool observation semantic failure defense. Intercepts HTTP 200 pseudo-success
business errors from MCP/REST tools, classifies them into retryable vs non-retryable
tiers, and elevates them into explicit ToolMessage warnings.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum

# Common success status codes / indicators that should not be flagged as failures
_SUCCESS_CODES: frozenset[int | str] = frozenset(
    {0, 200, 201, 204, "0", "200", "201", "204", "OK", "SUCCESS", "ok", "success"}
)

# Tool names that naturally emit exit codes, tests, search terms, or browser traces and must not be sniffed
_DEFAULT_EXEMPT_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "bash_code_execute_tool",
        "bash_process_tool",
        "file_read_tool",
        "file_write_tool",
        "file_edit_tool",
        "glob_tool",
        "grep_tool",
        "diff_tool",
        "web_search",
        "web_fetch",
        "fetch_web_content",
        "search_bm25",
        "ask_question",
        "clarification_ask_question",
    }
)

_RETRYABLE_KEYWORDS: tuple[str, ...] = (
    "rate limit",
    "too many requests",
    "throttled",
    "quota exceeded",
    "try again later",
    "temporarily unavailable",
    "service unavailable",
    "upstream timeout",
    "lock conflict",
    "optimistic lock",
    "busy",
    "deadlock",
    "concurrent",
    "retry later",
    "gateway timeout",
    "频率限制",
    "限流",
    "稍后重试",
    "暂不可用",
    "超时",
    "锁冲突",
    "乐观锁",
    "系统繁忙",
    "死锁",
    "并发冲突",
)

_NON_RETRYABLE_KEYWORDS: tuple[str, ...] = (
    "not found",
    "does not exist",
    "不存在",
    "未找到",
    "unauthorized",
    "forbidden",
    "permission denied",
    "access denied",
    "无权",
    "未授权",
    "invalid parameter",
    "validation error",
    "missing argument",
    "bad request",
    "非法参数",
    "参数错误",
    "缺少参数",
    "already exists",
    "已存在",
    "conflict",
    "duplicate",
    "重复",
)

_ERROR_MSG_KEYS: tuple[str, ...] = (
    "message",
    "error",
    "msg",
    "errMsg",
    "errmsg",
    "error_msg",
    "reason",
    "detail",
    "description",
)


class SemanticFailureType(str, Enum):
    """Classification of semantic business failures."""

    NONE = "none"
    RETRYABLE = "retryable_business_error"
    NON_RETRYABLE = "non_retryable_business_error"


@dataclass(frozen=True, slots=True)
class SemanticFailureSniffResult:
    """Outcome of analyzing a tool execution payload for business failures."""

    is_failure: bool
    failure_type: SemanticFailureType
    reason: str
    extracted_code: int | str | None = None
    extracted_message: str | None = None
    raw_payload: dict[str, object] | None = None


def should_skip_semantic_sniff(
    tool_name: str,
    *,
    metadata: dict[str, object] | None = None,
    tool_args: dict[str, object] | None = None,
) -> bool:
    """Determine whether a tool is exempt from observation failure sniffing."""
    if metadata and bool(metadata.get("skip_semantic_failure_sniffing")):
        return True
    if tool_args and bool(
        tool_args.get("skip_semantic_failure_sniffing")
        or tool_args.get("skip_semantic_sniff")
    ):
        return True
    if tool_name in _DEFAULT_EXEMPT_TOOL_NAMES:
        return True
    return tool_name.startswith(
        (
            "test_",
            "verify_",
            "check_system_",
            "memory_",
            "knowledge_",
            "browser_",
        )
    )


def _classify_tier(
    code: int | str | None,
    message: str,
    raw_text: str,
) -> SemanticFailureType:
    """Classify a detected business error into retryable vs non-retryable."""
    searchable = f"{code} {message} {raw_text}".lower()

    if code in (429, 502, 503, 504, "429", "502", "503", "504"):
        return SemanticFailureType.RETRYABLE

    for kw in _RETRYABLE_KEYWORDS:
        if kw in searchable:
            return SemanticFailureType.RETRYABLE

    if code in (400, 401, 403, 404, 422, "400", "401", "403", "404", "422"):
        return SemanticFailureType.NON_RETRYABLE

    for kw in _NON_RETRYABLE_KEYWORDS:
        if kw in searchable:
            return SemanticFailureType.NON_RETRYABLE

    # Default to non-retryable to avoid burning tokens on unrecognized domain errors
    return SemanticFailureType.NON_RETRYABLE


def _extract_error_detail(data: dict[str, object]) -> tuple[int | str | None, str]:
    """Extract code and error message from various dictionary conventions."""
    code: int | str | None = None
    for code_key in ("code", "errcode", "err_code", "errno", "status_code"):
        val = data.get(code_key)
        if isinstance(val, (int, str)):
            code = val
            break

    msg = ""
    for msg_key in _ERROR_MSG_KEYS:
        val = data.get(msg_key)
        if isinstance(val, str) and val.strip():
            msg = val.strip()
            break
        if isinstance(val, dict):
            inner_code, inner_msg = _extract_error_detail(val)
            if inner_code is not None and code is None:
                code = inner_code
            if inner_msg:
                msg = inner_msg
                break
        if isinstance(val, list) and val:
            first = val[0]
            if isinstance(first, str):
                msg = first
                break
            if isinstance(first, dict):
                inner_code, inner_msg = _extract_error_detail(first)
                if inner_code is not None and code is None:
                    code = inner_code
                if inner_msg:
                    msg = inner_msg
                    break

    if not msg and "errors" in data:
        errs = data["errors"]
        if isinstance(errs, list) and errs:
            first = errs[0]
            if isinstance(first, str):
                msg = first
            elif isinstance(first, dict):
                inner_code, inner_msg = _extract_error_detail(first)
                if inner_code is not None and code is None:
                    code = inner_code
                if inner_msg:
                    msg = inner_msg

    return code, msg


def _inspect_dict_payload(data: dict[str, object]) -> SemanticFailureSniffResult:
    """Recursively inspect top-level and first-level dictionary for business failure tokens."""
    # 1. Explicit boolean success indicator: {"success": false} / {"is_success": false}
    for flag_key in ("success", "is_success", "ok", "has_succeeded"):
        if flag_key in data:
            val = data[flag_key]
            if val is False or val in ("false", "False", 0, "0"):
                code, msg = _extract_error_detail(data)
                ftype = _classify_tier(code, msg, str(data))
                return SemanticFailureSniffResult(
                    is_failure=True,
                    failure_type=ftype,
                    reason=f"Explicit failure flag '{flag_key}={val}'",
                    extracted_code=code,
                    extracted_message=msg or None,
                    raw_payload=data,
                )

    # 2. Explicit status indicator: {"status": "error" | "failed" | "failure"}
    for status_key in ("status", "state", "result"):
        if status_key in data:
            val = data[status_key]
            if isinstance(val, str) and val.strip().lower() in ("error", "failed", "failure", "err", "fatal"):
                code, msg = _extract_error_detail(data)
                # Anti-False-Positive check: Distinguish RPC/Envelope failure from Domain Entity State.
                # E.g. {"task_id": "123", "status": "failed", "exit_code": 1} is a successful entity lookup,
                # whereas {"status": "error", "message": "unauthorized"} or {"status": "failed", "error": "not found"} is an RPC failure.
                has_entity_identifier = any(
                    k in data for k in ("id", "task_id", "job_id", "order_id", "build_id", "run_id", "device_id")
                )
                has_substantive_data = bool(data.get("data") or data.get("result") or data.get("records") or data.get("items"))
                has_explicit_error = bool(msg or "error" in data or "errors" in data or (code and code not in _SUCCESS_CODES))

                # If it's a domain entity query with entity identifier/data and no explicit error message, do not misclassify as RPC failure
                if (has_entity_identifier or has_substantive_data) and not has_explicit_error:
                    continue

                ftype = _classify_tier(code, msg, str(data))
                return SemanticFailureSniffResult(
                    is_failure=True,
                    failure_type=ftype,
                    reason=f"Explicit status '{status_key}={val}'",
                    extracted_code=code,
                    extracted_message=msg or None,
                    raw_payload=data,
                )

    # 3. Explicit error code indicator with non-success code
    for code_key in ("code", "errcode", "err_code", "errno", "status_code"):
        if code_key in data:
            code_val = data[code_key]
            if isinstance(code_val, (int, str)) and code_val not in _SUCCESS_CODES:
                code, msg = _extract_error_detail(data)
                # Only flag as failure if there is an error message, an error object, or absence of valid business data
                has_error_mention = bool(msg or "error" in data or "errors" in data)
                has_substantive_data = bool(data.get("data") or data.get("result") or data.get("records"))
                if has_error_mention or not has_substantive_data:
                    ftype = _classify_tier(code or code_val, msg, str(data))
                    return SemanticFailureSniffResult(
                        is_failure=True,
                        failure_type=ftype,
                        reason=f"Non-success code '{code_key}={code_val}'",
                        extracted_code=code or code_val,
                        extracted_message=msg or None,
                        raw_payload=data,
                    )

    # 4. Explicit error payload without success flag: {"error": "..."} / {"errors": [...]}
    if ("error" in data and data["error"] and data.get("success") is not True) or (
        "errors" in data and data["errors"] and data.get("data") is None
    ):
        code, msg = _extract_error_detail(data)
        ftype = _classify_tier(code, msg, str(data))
        reason = "Payload contains 'errors' array" if "errors" in data and not data.get("error") else "Payload contains root 'error' field"
        return SemanticFailureSniffResult(
            is_failure=True,
            failure_type=ftype,
            reason=reason,
            extracted_code=code,
            extracted_message=msg or None,
            raw_payload=data,
        )

    return SemanticFailureSniffResult(
        is_failure=False,
        failure_type=SemanticFailureType.NONE,
        reason="",
    )


def sniff_semantic_failure(
    content: object,
    *,
    tool_name: str = "",
    tool_metadata: dict[str, object] | None = None,
    tool_args: dict[str, object] | None = None,
) -> SemanticFailureSniffResult:
    """Analyze a tool return payload for business-level failures under HTTP 200."""
    if should_skip_semantic_sniff(tool_name, metadata=tool_metadata, tool_args=tool_args):
        return SemanticFailureSniffResult(
            is_failure=False,
            failure_type=SemanticFailureType.NONE,
            reason="Tool is exempt from semantic sniffing",
        )

    if isinstance(content, dict):
        return _inspect_dict_payload(content)

    if isinstance(content, str):
        trimmed = content.strip()
        if not trimmed:
            return SemanticFailureSniffResult(
                is_failure=False,
                failure_type=SemanticFailureType.NONE,
                reason="Content is empty",
            )

        # 1. Strip security boundary markers if content was wrapped
        if "<<<UNTRUSTED_DATA" in trimmed or "<<<TOOL_OUTPUT" in trimmed:
            from myrm_agent_harness.core.security.detection.content_boundary import (
                extract_wrapped_payload,
            )

            trimmed = extract_wrapped_payload(trimmed).strip()

        # 2. Strip markdown code fences if present (e.g. ```json ... ```)
        if trimmed.startswith("```"):
            lines = trimmed.splitlines()
            if len(lines) >= 2 and lines[0].startswith("```") and lines[-1].strip() == "```":
                trimmed = "\n".join(lines[1:-1]).strip()

        # Fast exit for non-JSON or obviously normal text
        if not (trimmed.startswith("{") and trimmed.endswith("}")):
            return SemanticFailureSniffResult(
                is_failure=False,
                failure_type=SemanticFailureType.NONE,
                reason="Content is not a JSON object",
            )
        # Fast check: skip parsing if typical tokens are completely absent
        if not any(
            token in trimmed for token in ('"success"', '"status"', '"code"', '"err', '"error"', '"errno"')
        ):
            return SemanticFailureSniffResult(
                is_failure=False,
                failure_type=SemanticFailureType.NONE,
                reason="Content lacks failure token signatures",
            )

        try:
            parsed = json.loads(trimmed)
            if isinstance(parsed, dict):
                return _inspect_dict_payload(parsed)
        except (ValueError, TypeError):
            pass

    return SemanticFailureSniffResult(
        is_failure=False,
        failure_type=SemanticFailureType.NONE,
        reason="No failure signature detected",
    )


def elevate_semantic_failure_observation(
    sniff_result: SemanticFailureSniffResult,
    raw_content: object,
) -> str:
    """Wrap a detected business failure into an elevated, unambiguous observation for the LLM."""
    if not sniff_result.is_failure:
        return str(raw_content)

    formatted_payload: str
    if sniff_result.raw_payload is not None:
        try:
            formatted_payload = json.dumps(sniff_result.raw_payload, ensure_ascii=False, indent=2)
        except Exception:
            formatted_payload = str(raw_content)
    else:
        formatted_payload = str(raw_content)

    is_retryable = sniff_result.failure_type == SemanticFailureType.RETRYABLE
    tier_label = "RETRYABLE (transient system state)" if is_retryable else "NON-RETRYABLE (permanent business failure)"
    action_guidance = (
        "3. Action Guidance: This error is transient (e.g. rate limit, lock conflict). "
        "You may retry after a backoff, or notify the user of the temporary disruption."
        if is_retryable
        else "3. Action Guidance: This is a permanent business rejection (e.g. not found, forbidden, invalid argument). "
        "Do NOT retry with the identical parameters. Adjust your strategy, query alternative resources, or honestly report the failure to the user."
    )

    code_str = f" [Code: {sniff_result.extracted_code}]" if sniff_result.extracted_code is not None else ""
    msg_str = f" [Message: {sniff_result.extracted_message}]" if sniff_result.extracted_message else ""

    return (
        f"[SYSTEM OBSERVATION ELEVATION: TARGET SYSTEM REPORTED BUSINESS FAILURE]\n"
        f"Transport Status: HTTP 200 / Communication Succeeded\n"
        f"Business Status: FAILURE ({sniff_result.reason}){code_str}{msg_str}\n"
        f"Error Classification: {tier_label}\n"
        f"Target System Payload:\n"
        f"```json\n"
        f"{formatted_payload}\n"
        f"```\n\n"
        f"CRITICAL AGENT RULES:\n"
        f"1. The target system explicitly failed to fulfill this operation.\n"
        f"2. Strict Grounding: NEVER hallucinate that the record exists, or that the action succeeded.\n"
        f"{action_guidance}"
    )
