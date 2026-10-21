"""Double-layer error preservation and diagnostic envelope generator.

Faithfully addresses the root cause benchmarked against IHUI-AI commit 6ce28c444:
- Intercepts raw stream parsing failures (e.g. JSONDecodeError, ConnectionResetError, BrokenPipe).
- Encapsulates the raw root cause into a NestedStreamException without loss of stack or chunk context.
- Determines retry eligibility based on whether the error represents a transient transport/chunk glitch.
- Produces actionable GitHub Flavored Markdown diagnostic cards for UI and devtools.

[OUTPUT]
- DoubleLayerErrorPreserver: Diagnostic engine preserving inner cause and outer context.

[INPUT]
- __future__
- json

[OUTPUT]
- DoubleLayerErrorPreserver

[POS]
Double-layer error preservation and diagnostic envelope generator.
"""

from __future__ import annotations

import json

from myrm_agent_harness.runtime.stream_resilience.stream_error_types import (
    NestedStreamError,
    StreamErrorKind,
)


class DoubleLayerErrorPreserver:
    """Safeguards stream error transparency by preventing silent exception swallowing."""

    @staticmethod
    def is_transient_error(exc: BaseException) -> bool:
        """Classify whether an exception stems from a retriable network or transient glitch."""
        exc_name = type(exc).__name__
        exc_str = str(exc).lower()

        # Transient socket / connection errors
        if isinstance(exc, (ConnectionResetError, BrokenPipeError, TimeoutError)):
            return True

        if any(
            token in exc_str
            for token in (
                "connection reset",
                "broken pipe",
                "socket hang up",
                "econnreset",
                "etimedout",
                "timeout",
                "server disconnected",
            )
        ):
            return True

        # Transient HTTP upstream status codes
        if any(code in exc_str for code in ("502", "503", "504", "429")):
            return True

        # Malformed / truncated chunk mid-stream is retriable from last sequence
        return bool(isinstance(exc, json.JSONDecodeError) or "jsondecodeerror" in exc_name.lower())

    @classmethod
    def wrap_exception(
        cls,
        exc: BaseException,
        raw_chunk: str = "",
        last_acked_seq: int = -1,
    ) -> NestedStreamError:
        """Wrap an arbitrary caught exception into a structured NestedStreamError."""
        cause_name = type(exc).__name__
        cause_str = str(exc)
        is_retriable = cls.is_transient_error(exc)

        # Categorize into StreamErrorKind
        if isinstance(exc, (ConnectionResetError, BrokenPipeError)) or "reset" in cause_str.lower():
            kind = StreamErrorKind.TRANSPORT_RESET
            outer_msg = "传输层连接异常重置，底层 Socket 提前关闭"
        elif isinstance(exc, TimeoutError) or "timeout" in cause_str.lower():
            kind = StreamErrorKind.TIMEOUT
            outer_msg = "流式数据包接收超时，未在指定心跳窗口内收到 Chunk"
        elif isinstance(exc, json.JSONDecodeError) or "json" in cause_name.lower():
            kind = StreamErrorKind.MALFORMED_CHUNK
            outer_msg = "流式数据帧格式畸变，无法解析为合法 JSON 结构"
        elif any(code in cause_str for code in ("502", "503", "504", "429")):
            kind = StreamErrorKind.UPSTREAM_API_ERROR
            outer_msg = "上游模型提供方服务暂时不可用或触发频控"
        else:
            kind = StreamErrorKind.PROTOCOL_VIOLATION
            outer_msg = "流式通信协议异常，未收到合规的事件流帧"

        preview = raw_chunk[:200] + "..." if len(raw_chunk) > 200 else raw_chunk

        return NestedStreamError(
            error_kind=kind,
            outer_message=outer_msg,
            cause_error_name=cause_name,
            cause_details=cause_str,
            is_retriable=is_retriable,
            raw_chunk_preview=preview,
            last_acked_seq=last_acked_seq,
        )

    @staticmethod
    def render_diagnostic_markdown(nested_exc: NestedStreamError) -> str:
        """Render a GitHub Flavored Markdown diagnostic card for end users and developers."""
        lines: list[str] = [
            "### 🚨 流式通信双层异常链路诊断卡片",
            f"- **外层分类**: `{nested_exc.error_kind.value}`",
            f"- **外层语义**: {nested_exc.outer_message}",
            f"- **底层根因类型**: `{nested_exc.cause_error_name}`",
            f"- **底层原始报错**: `{nested_exc.cause_details}`",
            f"- **已确认序列号 (ACK Seq)**: `{nested_exc.last_acked_seq}`",
            f"- **是否允许断点自愈重试**: `{'✅ 允许重试' if nested_exc.is_retriable else '❌ 不可重试 (终止)'}`",
            "",
        ]

        if nested_exc.raw_chunk_preview:
            lines.extend(
                [
                    "```text",
                    f"截获异常 Chunk 前缀: {nested_exc.raw_chunk_preview}",
                    "```",
                    "",
                ]
            )

        if nested_exc.is_retriable:
            lines.extend(
                [
                    "> [!NOTE]",
                    f"> 检测到瞬态通信异常。系统将基于序列号 `seq > {nested_exc.last_acked_seq}` 自动触发带退避的断点续流重连。",
                ]
            )
        else:
            lines.extend(
                [
                    "> [!CAUTION]",
                    "> 检测到不可自动恢复的致命错误（如认证失效或协议冲突），请检查凭据与请求载荷。",
                ]
            )

        return "\n".join(lines)
