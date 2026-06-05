"""LLM error diagnostic engine.

Classifies LLM errors and produces localized DiagnosticResult with resolution steps.
"""

import re

from myrm_agent_harness.agent.errors.diagnostics.i18n import get_locale_manager
from myrm_agent_harness.agent.errors.diagnostics.types import (
    DiagnosticResult,
    ErrorContext,
)


class LLMErrorDiagnostic:
    """LLM错误智能诊断器

    Example:
        >>> # 基础诊断(无上下文)
        >>> try:
        ...     # LLM调用
        ...     pass
        ... except Exception as e:
        ...     result = LLMErrorDiagnostic.diagnose(e)
        ...     print(result.user_message)
        ...
        >>> # 精准诊断(带ErrorContext, 支持自定义端点)
        >>> from myrm_agent_harness.agent.errors.diagnostics import ErrorContext
        >>> try:
        ...     # Ollama调用
        ...     pass
        ... except Exception as e:
        ...     context = ErrorContext(
        ...         model_name="llama3.2",
        ...         is_custom_endpoint=True,
        ...         base_url="http://localhost:11434"
        ...     )
        ...     result = LLMErrorDiagnostic.diagnose(e, context)
        ...     print(result.user_message)  # "Unable to connect to Ollama (http://localhost:11434)"
    """

    @staticmethod
    def diagnose(
        exc: Exception,
        context: ErrorContext | None = None,
        locale: str | None = None,
        cooldown_remaining_ms: int | None = None,
    ) -> DiagnosticResult:
        """诊断LLM错误并返回清晰的解决方案

        Args:
            exc: LLM调用产生的异常
            context: 错误上下文(可选, 用于精准诊断)
            locale: 语言代码(可选, None=自动检测)
            cooldown_remaining_ms: 冷却剩余时间(毫秒, 可选)

        Returns:
            DiagnosticResult: 错误诊断结果
        """
        locale_manager = get_locale_manager()
        if locale is None:
            locale = locale_manager.detect_locale()

        error_str = str(exc).lower()
        error_repr = repr(exc).lower()
        full_text = f"{error_str} {error_repr}"

        # 1. Connection errors (精准自定义端点诊断)
        if any(
            kw in full_text
            for kw in [
                "connection refused",
                "connection reset",
                "connection error",
                "failed to establish",
            ]
        ):
            # 自定义端点(Ollama/LM Studio)专属诊断
            if context and context.is_custom_endpoint:
                service_name = LLMErrorDiagnostic._infer_service_name(context.base_url)
                base_url_display = context.base_url or "custom endpoint"
                port = LLMErrorDiagnostic._extract_port(context.base_url)

                params = {
                    "service_name": service_name,
                    "base_url_display": base_url_display,
                    "port": port,
                }

                user_message = locale_manager.translate("custom_endpoint_unreachable", "user_message", locale, **params)
                resolution_steps = locale_manager.translate(
                    "custom_endpoint_unreachable", "resolution_steps", locale, **params
                )

                cooldown_hint = LLMErrorDiagnostic._format_cooldown_hint(cooldown_remaining_ms, locale)
                user_message += cooldown_hint

                return DiagnosticResult(
                    error_type="custom_endpoint_unreachable",
                    user_message=user_message,
                    resolution_steps=resolution_steps,
                    is_retryable=True,
                    locale=locale,
                )

            # 通用连接错误诊断
            user_message = locale_manager.translate("connection", "user_message", locale)
            resolution_steps = locale_manager.translate("connection", "resolution_steps", locale)

            cooldown_hint = LLMErrorDiagnostic._format_cooldown_hint(cooldown_remaining_ms, locale)
            user_message += cooldown_hint

            return DiagnosticResult(
                error_type="connection",
                user_message=user_message,
                resolution_steps=resolution_steps,
                is_retryable=True,
                locale=locale,
            )

        # 2. Billing / insufficient balance errors
        billing_keywords = [
            "billing",
            "insufficient balance",
            "insufficient funds",
            "insufficient credits",
            "insufficient quota",
            "payment required",
            "exceeded your current quota",
            "exceeded quota",
            "credit balance",
            "account is deactivated",
            "top up your credits",
            "余额不足",
            "额度不足",
            "欠费",
            "请充值",
        ]
        if any(kw in full_text for kw in billing_keywords) or re.search(r"(?<!\d)402(?!\d)", full_text):
            user_message = locale_manager.translate("billing", "user_message", locale)
            resolution_steps = locale_manager.translate("billing", "resolution_steps", locale)

            cooldown_hint = LLMErrorDiagnostic._format_cooldown_hint(cooldown_remaining_ms, locale)
            user_message += cooldown_hint

            return DiagnosticResult(
                error_type="billing",
                user_message=user_message,
                resolution_steps=resolution_steps,
                is_retryable=False,
                locale=locale,
            )

        # 3. API key errors
        api_key_keywords = [
            "invalid api key",
            "authentication failed",
            "unauthorized",
        ]
        if any(kw in full_text for kw in api_key_keywords) or re.search(r"(?<!\d)(401|403)(?!\d)", full_text):
            user_message = locale_manager.translate("api_key", "user_message", locale)
            resolution_steps = locale_manager.translate("api_key", "resolution_steps", locale)

            cooldown_hint = LLMErrorDiagnostic._format_cooldown_hint(cooldown_remaining_ms, locale)
            user_message += cooldown_hint

            return DiagnosticResult(
                error_type="api_key",
                user_message=user_message,
                resolution_steps=resolution_steps,
                is_retryable=False,
                locale=locale,
            )

        # 4. Model not found (精准自定义端点诊断)
        model_keywords = ["model not found", "model does not exist", "unknown model"]
        if (
            any(kw in full_text for kw in model_keywords)
            or re.search(r"(?<!\d)404(?!\d)", full_text)
            or ("model" in full_text and "not found" in full_text)
        ):
            if context and context.model_name:
                model_name = context.model_name
            else:
                model_match = re.search(r"model[:\s]+([a-zA-Z0-9\-._/]+)", full_text)
                model_name = model_match.group(1) if model_match else "unknown"

            # 自定义端点(Ollama/LM Studio)专属诊断
            if context and context.is_custom_endpoint:
                service_name = LLMErrorDiagnostic._infer_service_name(context.base_url)
                params = {"model_name": model_name, "service_name": service_name}

                user_message = locale_manager.translate("custom_model_not_found", "user_message", locale, **params)
                resolution_steps = locale_manager.translate(
                    "custom_model_not_found", "resolution_steps", locale, **params
                )

                cooldown_hint = LLMErrorDiagnostic._format_cooldown_hint(cooldown_remaining_ms, locale)
                user_message += cooldown_hint

                return DiagnosticResult(
                    error_type="custom_model_not_found",
                    user_message=user_message,
                    resolution_steps=resolution_steps,
                    is_retryable=False,
                    locale=locale,
                )

            # 通用模型未找到诊断
            params = {"model_name": model_name}
            user_message = locale_manager.translate("model", "user_message", locale, **params)
            resolution_steps = locale_manager.translate("model", "resolution_steps", locale, **params)

            cooldown_hint = LLMErrorDiagnostic._format_cooldown_hint(cooldown_remaining_ms, locale)
            user_message += cooldown_hint

            return DiagnosticResult(
                error_type="model",
                user_message=user_message,
                resolution_steps=resolution_steps,
                is_retryable=True,
                locale=locale,
            )

        # 5. Rate limit
        rate_limit_keywords = ["rate limit", "too many requests", "quota exceeded"]
        if any(kw in full_text for kw in rate_limit_keywords) or re.search(r"(?<!\d)429(?!\d)", full_text):
            user_message = locale_manager.translate("rate_limit", "user_message", locale)
            resolution_steps = locale_manager.translate("rate_limit", "resolution_steps", locale)

            cooldown_hint = LLMErrorDiagnostic._format_cooldown_hint(cooldown_remaining_ms, locale)
            user_message += cooldown_hint

            return DiagnosticResult(
                error_type="rate_limit",
                user_message=user_message,
                resolution_steps=resolution_steps,
                is_retryable=True,
                locale=locale,
            )

        # 6. Response format error
        if any(
            kw in full_text
            for kw in [
                "must be in json format",
                "schema validation error",
                "invalid json format",
                "malformed json",
            ]
        ):
            user_message = locale_manager.translate("response_format_error", "user_message", locale)
            resolution_steps = locale_manager.translate("response_format_error", "resolution_steps", locale)

            cooldown_hint = LLMErrorDiagnostic._format_cooldown_hint(cooldown_remaining_ms, locale)
            user_message += cooldown_hint

            return DiagnosticResult(
                error_type="response_format_error",
                user_message=user_message,
                resolution_steps=resolution_steps,
                is_retryable=True,
                locale=locale,
            )

        # 7. Context overflow
        if any(
            kw in full_text
            for kw in [
                "context length",
                "token limit",
                "context window",
                "too long",
                "max tokens",
            ]
        ):
            user_message = locale_manager.translate("context_overflow", "user_message", locale)
            resolution_steps = locale_manager.translate("context_overflow", "resolution_steps", locale)

            cooldown_hint = LLMErrorDiagnostic._format_cooldown_hint(cooldown_remaining_ms, locale)
            user_message += cooldown_hint

            return DiagnosticResult(
                error_type="context_overflow",
                user_message=user_message,
                resolution_steps=resolution_steps,
                is_retryable=True,
                locale=locale,
            )

        # 8. Timeout
        if any(kw in full_text for kw in ["timeout", "timed out", "time out"]):
            user_message = locale_manager.translate("timeout", "user_message", locale)
            resolution_steps = locale_manager.translate("timeout", "resolution_steps", locale)

            cooldown_hint = LLMErrorDiagnostic._format_cooldown_hint(cooldown_remaining_ms, locale)
            user_message += cooldown_hint

            return DiagnosticResult(
                error_type="timeout",
                user_message=user_message,
                resolution_steps=resolution_steps,
                is_retryable=True,
                locale=locale,
            )

        # 9. Generic fallback
        params = {"error_message": str(exc)[:200]}
        user_message = locale_manager.translate("unknown", "user_message", locale, **params)
        resolution_steps = locale_manager.translate("unknown", "resolution_steps", locale)

        cooldown_hint = LLMErrorDiagnostic._format_cooldown_hint(cooldown_remaining_ms, locale)
        user_message += cooldown_hint

        return DiagnosticResult(
            error_type="unknown",
            user_message=user_message,
            resolution_steps=resolution_steps,
            is_retryable=False,
            locale=locale,
        )

    @staticmethod
    def diagnose_truncation(
        truncation_type: str,
        locale: str | None = None,
    ) -> DiagnosticResult:
        """Diagnose length truncation scenarios.

        Args:
            truncation_type: One of "thinking_budget_exhausted", "tool_call_truncated",
                "tool_call_retry", "text_continuation", "text_continuation_exhausted"
            locale: Language code (None = auto-detect)

        Returns:
            DiagnosticResult with localized user message and resolution steps.
        """
        locale_manager = get_locale_manager()
        if locale is None:
            locale = locale_manager.detect_locale()

        user_message = locale_manager.translate(truncation_type, "user_message", locale)
        resolution_steps = locale_manager.translate(truncation_type, "resolution_steps", locale)

        return DiagnosticResult(
            error_type=truncation_type,
            user_message=user_message,
            resolution_steps=resolution_steps,
            is_retryable=False,
            locale=locale,
        )

    @staticmethod
    def _infer_service_name(base_url: str | None) -> str:
        """推断服务名称(Ollama/LM Studio/vLLM/自定义LLM服务)"""
        if not base_url:
            return "custom LLM service"

        base_url_lower = base_url.lower()

        if "11434" in base_url_lower:
            return "Ollama"
        elif "1234" in base_url_lower:
            return "LM Studio"
        elif "vllm" in base_url_lower:
            return "vLLM"
        else:
            return "custom LLM service"

    @staticmethod
    def _extract_port(base_url: str | None) -> str:
        """提取端口号"""
        if not base_url:
            return "unknown"

        port_match = re.search(r":(\d+)", base_url)
        return port_match.group(1) if port_match else "unknown"

    @staticmethod
    def _format_cooldown_hint(cooldown_remaining_ms: int | None, locale: str) -> str:
        """生成cooldown提示(如果存在)"""
        if not cooldown_remaining_ms or cooldown_remaining_ms <= 0:
            return ""

        locale_manager = get_locale_manager()
        cooldown_seconds = int(cooldown_remaining_ms / 1000)

        hint_key = "single" if cooldown_seconds == 1 else "plural"

        try:
            cooldown_translations = locale_manager._translations.get(locale, {}).get("_cooldown_hint", {})
            if not cooldown_translations:
                cooldown_translations = locale_manager._translations.get("en", {}).get("_cooldown_hint", {})

            hint_template = cooldown_translations.get(hint_key, "")
            return hint_template.format(seconds=cooldown_seconds)
        except Exception:
            return f" Retry after {cooldown_seconds} seconds."
