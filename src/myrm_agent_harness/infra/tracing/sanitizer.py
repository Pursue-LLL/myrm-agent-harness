"""Three-layer progressive privacy sanitizer for OpenTelemetry spans and trace events.

[INPUT]
- myrm_agent_harness.core.security.redact.engine::redact_sensitive_text (POS: 敏感凭证正则脱敏基座)

[OUTPUT]
- TraceSpanSanitizer: 三层渐进式 Trace 属性与 Payload 脱敏清洗器
- SanitizingSpanProcessor: OpenTelemetry 导出前脱敏 Span 处理器
- sanitize_trace_attributes: 顶层无状态 Span 属性清洗快捷函数
- sanitize_trace_payload: 任意嵌套 JSONL / EventLog 追踪数据安全清洗器

[POS]
实现 Agent Tracing 规范中的“先脱敏再落盘”三层隐私防护体系：
第一层：高危敏感字段键名识别与安全命名空间放行；
第二层：敏感凭据值深度正则扫描（API Key / Bearer / 连接串 / 密码）；
第三层：超长大文本有界哈希截断与 SHA-256 指纹保全。
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

from myrm_agent_harness.core.security.redact.engine import redact_sensitive_text

try:
    from opentelemetry.context import Context
    from opentelemetry.sdk.trace import ReadableSpan, Span, SpanProcessor

    HAS_OTEL_SDK = True
except (ImportError, TypeError):
    HAS_OTEL_SDK = False
    SpanProcessor = object  # type: ignore
    ReadableSpan = Any  # type: ignore
    Span = Any  # type: ignore
    Context = Any  # type: ignore

type AttributePrimitive = str | int | float | bool
type AttributeValue = AttributePrimitive | Sequence[AttributePrimitive]

# 标准安全前缀白名单（符合 OTel GenAI 与常见语义命名空间）
_SAFE_KEY_PREFIXES: tuple[str, ...] = (
    "gen_ai.",
    "myrm.",
    "http.",
    "rpc.",
    "service.",
    "net.",
    "code.",
    "error.",
    "session.",
    "task.",
    "tool.",
)

# 显式高危关键字（若键名包含这些且不在安全命名空间，强制脱敏或丢弃）
_SENSITIVE_KEY_KEYWORDS: tuple[str, ...] = (
    "secret",
    "token",
    "password",
    "credential",
    "private_key",
    "auth_header",
    "authorization",
    "cookie",
    "api_key",
    "apikey",
    "secret_key",
    "access_key",
    "private_key",
    "key",
)

_BEARER_PATTERN = re.compile(r"Bearer\s+([A-Za-z0-9._~+/-]+=*)", re.IGNORECASE)


class TraceSpanSanitizer:
    """Three-layer progressive privacy sanitizer for trace spans and event logs."""

    def __init__(
        self,
        max_value_len: int = 2048,
        safe_prefixes: tuple[str, ...] = _SAFE_KEY_PREFIXES,
    ) -> None:
        self._max_value_len = max(max_value_len, 128)
        self._safe_prefixes = safe_prefixes

    def is_safe_key(self, key: str) -> bool:
        """Evaluate if an attribute key belongs to safe namespaces."""
        lower_key = key.lower()
        if any(lower_key.startswith(prefix) for prefix in self._safe_prefixes):
            return True
        return not any(keyword in lower_key for keyword in _SENSITIVE_KEY_KEYWORDS)

    def sanitize_string_value(self, val: str) -> str:
        """Apply pattern-based redaction and bounded SHA-256 truncation."""
        if not val:
            return val

        # Handle nested stringified JSON if applicable
        stripped = val.strip()
        if (stripped.startswith("{") and stripped.endswith("}")) or (
            stripped.startswith("[") and stripped.endswith("]")
        ):
            try:
                parsed = json.loads(val)
                if isinstance(parsed, dict):
                    sanitized_dict = self.sanitize_payload(parsed)
                    val = json.dumps(sanitized_dict, ensure_ascii=False)
                elif isinstance(parsed, list):
                    sanitized_list = [
                        self.sanitize_payload(item)
                        if isinstance(item, Mapping)
                        else (
                            self.sanitize_string_value(item)
                            if isinstance(item, str)
                            else item
                        )
                        for item in parsed
                    ]
                    val = json.dumps(sanitized_list, ensure_ascii=False)
            except Exception:
                pass

        # Layer 2: Sensitive value pattern scrubbing
        redacted = redact_sensitive_text(val)
        redacted = _BEARER_PATTERN.sub("Bearer [REDACTED_BEARER_TOKEN]", redacted)
        # Layer 3: Bounded truncation with integrity fingerprint
        length = len(redacted)
        if length > self._max_value_len:
            head_len = self._max_value_len // 2
            fp = hashlib.sha256(redacted.encode("utf-8")).hexdigest()[:8]
            return f"{redacted[:head_len]}... [TRUNCATED:len={length}:sha256={fp}]"
        return redacted

    def sanitize_attribute_value(self, val: AttributeValue) -> AttributeValue:
        """Scrub scalar or sequence attribute values preserving primitive types."""
        if isinstance(val, str):
            return self.sanitize_string_value(val)
        if isinstance(val, (int, float, bool)):
            return val
        if isinstance(val, (list, tuple)):
            sanitized_list: list[AttributePrimitive] = []
            for item in val:
                if isinstance(item, str):
                    sanitized_list.append(self.sanitize_string_value(item))
                elif isinstance(item, (int, float, bool)):
                    sanitized_list.append(item)
            return sanitized_list
        return str(val)

    def sanitize_attributes(
        self,
        attributes: Mapping[str, AttributeValue],
    ) -> dict[str, AttributeValue]:
        """Layer 1 + 2 + 3 combined sanitization over span attributes."""
        sanitized: dict[str, AttributeValue] = {}
        for k, v in attributes.items():
            lower_k = k.lower()
            if any(keyword in lower_k for keyword in _SENSITIVE_KEY_KEYWORDS) and not any(
                lower_k.startswith(p) for p in self._safe_prefixes
            ):
                # High-risk raw key blocked
                sanitized[k] = "[REDACTED_SENSITIVE_KEY]"
                continue
            sanitized[k] = self.sanitize_attribute_value(v)
        return sanitized

    def sanitize_payload(self, payload: Mapping[str, object]) -> dict[str, object]:
        """Recursively scrub arbitrary JSON-serializable payloads for trace export."""
        sanitized: dict[str, object] = {}
        for k, v in payload.items():
            str_k = str(k).lower()
            if any(term in str_k for term in _SENSITIVE_KEY_KEYWORDS) and not any(
                str_k.startswith(p) for p in self._safe_prefixes
            ):
                sanitized[k] = "[REDACTED_SENSITIVE_KEY]"
            elif isinstance(v, str):
                sanitized[k] = self.sanitize_string_value(v)
            elif isinstance(v, (int, float, bool)) or v is None:
                sanitized[k] = v
            elif isinstance(v, Mapping):
                sanitized[k] = self.sanitize_payload(v)
            elif isinstance(v, (list, tuple)):
                sanitized[k] = [
                    self.sanitize_string_value(item)
                    if isinstance(item, str)
                    else self.sanitize_payload(item)
                    if isinstance(item, Mapping)
                    else item
                    for item in v
                ]
            else:
                sanitized[k] = self.sanitize_string_value(str(v))
        return sanitized


_DEFAULT_SANITIZER = TraceSpanSanitizer()


def sanitize_trace_attributes(
    attributes: Mapping[str, AttributeValue],
) -> dict[str, AttributeValue]:
    """Pure convenience helper to sanitize span attributes via default sanitizer."""
    return _DEFAULT_SANITIZER.sanitize_attributes(attributes)


def sanitize_trace_payload(payload: Mapping[str, object]) -> dict[str, object]:
    """Pure convenience helper to sanitize trace event payloads via default sanitizer."""
    return _DEFAULT_SANITIZER.sanitize_payload(payload)


class SanitizingSpanProcessor(SpanProcessor):
    """OpenTelemetry SpanProcessor that scrubs sensitive attributes before downstream export."""

    def __init__(
        self,
        sanitizer: TraceSpanSanitizer | None = None,
        max_value_len: int | None = None,
    ) -> None:
        if sanitizer is not None:
            self._sanitizer = sanitizer
        elif max_value_len is not None:
            self._sanitizer = TraceSpanSanitizer(max_value_len=max_value_len)
        else:
            self._sanitizer = _DEFAULT_SANITIZER

    def on_start(self, span: Span, parent_context: Context | None = None) -> None:
        pass

    def on_end(self, span: ReadableSpan) -> None:
        attrs = getattr(span, "_attributes", None)
        if attrs is not None:
            inner_dict = getattr(attrs, "_dict", None)
            if isinstance(inner_dict, dict):
                sanitized = self._sanitizer.sanitize_attributes(inner_dict)
                inner_dict.clear()
                inner_dict.update(sanitized)
            elif isinstance(attrs, Mapping):
                sanitized = self._sanitizer.sanitize_attributes(attrs)
                try:
                    object.__setattr__(span, "_attributes", sanitized)
                except Exception:
                    pass

    def shutdown(self) -> None:
        pass

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return True
