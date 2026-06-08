"""测试LLM错误智能诊断系统"""

from myrm_agent_harness.agent.errors.diagnostics import LLMErrorDiagnostic


def test_diagnose_connection_error():
    """测试连接错误诊断"""
    exc = ConnectionRefusedError("Connection refused on localhost:11434")
    result = LLMErrorDiagnostic.diagnose(exc)

    assert result.error_type == "connection"
    assert "Unable to connect" in result.user_message
    assert len(result.resolution_steps) > 0
    assert any("ollama serve" in step.lower() for step in result.resolution_steps)
    assert result.is_retryable is True


def test_diagnose_api_key_error():
    """测试API key错误诊断"""
    exc = ValueError("Invalid API key: authentication failed (401)")
    result = LLMErrorDiagnostic.diagnose(exc)

    assert result.error_type == "api_key"
    assert "authentication failed" in result.user_message.lower()
    assert len(result.resolution_steps) > 0
    assert any("API key" in step for step in result.resolution_steps)
    assert result.is_retryable is False


def test_diagnose_model_not_found():
    """测试模型未找到错误诊断"""
    exc = ValueError("Model llama3.2 does not exist (404)")
    result = LLMErrorDiagnostic.diagnose(exc)

    assert result.error_type == "model"
    assert "llama3.2" in result.user_message
    assert len(result.resolution_steps) > 0
    assert any("ollama pull" in step.lower() for step in result.resolution_steps)
    assert result.is_retryable is True


def test_diagnose_rate_limit_error():
    """测试速率限制错误诊断"""
    exc = Exception("Rate limit exceeded: too many requests (429)")
    result = LLMErrorDiagnostic.diagnose(exc)

    assert result.error_type == "rate_limit"
    assert "rate limit" in result.user_message.lower()
    assert len(result.resolution_steps) > 0
    assert any("60 seconds" in step for step in result.resolution_steps)
    assert result.is_retryable is True


def test_diagnose_billing_error_openai():
    """测试 OpenAI 余额不足错误诊断"""
    exc = Exception("You exceeded your current quota, please check your plan and billing details (402)")
    result = LLMErrorDiagnostic.diagnose(exc)

    assert result.error_type == "billing"
    assert "balance" in result.user_message.lower() or "insufficient" in result.user_message.lower()
    assert len(result.resolution_steps) == 3
    assert result.is_retryable is False


def test_diagnose_billing_error_deepseek():
    """测试 DeepSeek 余额不足错误诊断（中文关键词）"""
    exc = Exception("余额不足，请充值后再试")
    result = LLMErrorDiagnostic.diagnose(exc)

    assert result.error_type == "billing"
    assert result.is_retryable is False


def test_diagnose_billing_error_anthropic():
    """测试 Anthropic insufficient credits 错误诊断"""
    exc = Exception("Your account has insufficient credits to complete this request")
    result = LLMErrorDiagnostic.diagnose(exc)

    assert result.error_type == "billing"
    assert result.is_retryable is False


def test_diagnose_context_overflow():
    """测试上下文溢出错误诊断"""
    exc = ValueError("Context length 150000 exceeds model limit 128000")
    result = LLMErrorDiagnostic.diagnose(exc)

    assert result.error_type == "context_overflow"
    assert "context length" in result.user_message.lower() or "exceeds" in result.user_message.lower()
    assert len(result.resolution_steps) > 0
    assert any("compression" in step.lower() for step in result.resolution_steps)
    assert result.is_retryable is True


def test_diagnose_timeout_error():
    """测试超时错误诊断"""
    exc = TimeoutError("Request timed out after 30 seconds")
    result = LLMErrorDiagnostic.diagnose(exc)

    assert result.error_type == "timeout"
    assert "timed out" in result.user_message.lower()
    assert len(result.resolution_steps) > 0
    assert any("timeout_seconds" in step for step in result.resolution_steps)
    assert result.is_retryable is True


def test_diagnose_unknown_error():
    """测试未知错误诊断（fallback）"""
    exc = RuntimeError("Some random error message")
    result = LLMErrorDiagnostic.diagnose(exc)

    assert result.error_type == "unknown"
    assert "Some random error message" in result.user_message
    assert len(result.resolution_steps) > 0
    assert result.is_retryable is False


def test_diagnose_case_insensitive():
    """测试大小写不敏感"""
    exc = Exception("CONNECTION REFUSED ON LOCALHOST")
    result = LLMErrorDiagnostic.diagnose(exc)

    # 应该识别为connection错误
    assert result.error_type == "connection"
    assert result.is_retryable is True


def test_diagnostic_result_immutable():
    """测试DiagnosticResult不可变性"""
    from myrm_agent_harness.agent.errors.diagnostics import DiagnosticResult

    result = DiagnosticResult(
        error_type="test", user_message="test message", resolution_steps=["step1"], is_retryable=True, locale="en"
    )

    # 应该抛出AttributeError（frozen=True）
    try:
        result.error_type = "new_type"  # type: ignore[misc]
        assert False, "Should have raised AttributeError"
    except AttributeError:
        pass


def test_custom_endpoint_connection_refused_ollama():
    """测试自定义端点（Ollama）连接拒绝错误的精准诊断"""
    from myrm_agent_harness.agent.errors.diagnostics import ErrorContext

    exc = ConnectionRefusedError("Connection refused on localhost:11434")
    context = ErrorContext(model_name="llama3.2", is_custom_endpoint=True, base_url="http://localhost:11434")

    result = LLMErrorDiagnostic.diagnose(exc, context)

    # 验证错误类型
    assert result.error_type == "custom_endpoint_unreachable"
    # 验证精准的服务名称识别
    assert "Ollama" in result.user_message
    assert "http://localhost:11434" in result.user_message
    # 验证精准的resolution steps
    assert any("Ollama service is running" in step for step in result.resolution_steps)
    assert any("http://localhost:11434/v1/models" in step for step in result.resolution_steps)
    assert any("11434" in step for step in result.resolution_steps)
    assert result.is_retryable is True


def test_custom_endpoint_model_not_found():
    """测试自定义端点模型未找到错误的精准诊断"""
    from myrm_agent_harness.agent.errors.diagnostics import ErrorContext

    exc = ValueError("Model llama3.2 does not exist (404)")
    context = ErrorContext(model_name="llama3.2", is_custom_endpoint=True, base_url="http://localhost:1234")

    result = LLMErrorDiagnostic.diagnose(exc, context)

    # 验证错误类型
    assert result.error_type == "custom_model_not_found"
    # 验证精准的服务名称识别（LM Studio）
    assert "LM Studio" in result.user_message
    assert "llama3.2" in result.user_message
    # 验证精准的resolution steps
    assert any("ollama list" in step.lower() or "LM Studio" in step for step in result.resolution_steps)
    assert any("case-sensitive" in step.lower() for step in result.resolution_steps)
    assert result.is_retryable is False


def test_error_context_immutable():
    """测试ErrorContext不可变性"""
    from myrm_agent_harness.agent.errors.diagnostics import ErrorContext

    context = ErrorContext(model_name="test", is_custom_endpoint=True, base_url="http://localhost:11434")

    # 应该抛出AttributeError（frozen=True）
    try:
        context.model_name = "new_model"  # type: ignore[misc]
        assert False, "Should have raised AttributeError"
    except AttributeError:
        pass


def test_diagnose_response_format_error():
    """测试响应格式错误诊断"""
    exc = ValueError("400 Bad Request: must be in JSON format")
    result = LLMErrorDiagnostic.diagnose(exc)

    assert result.error_type == "response_format_error"
    assert "validation failed" in result.user_message.lower() or "format" in result.user_message.lower()
    assert len(result.resolution_steps) > 0
    assert any("fallback" in step.lower() for step in result.resolution_steps)
    assert result.is_retryable is True


def test_diagnose_response_format_error_zh():
    """测试响应格式错误诊断（中文）"""
    exc = ValueError("schema validation error")
    result = LLMErrorDiagnostic.diagnose(exc, locale="zh-CN")

    assert result.error_type == "response_format_error"
    assert "模型输出" in result.user_message or "验证失败" in result.user_message
    assert result.locale == "zh-CN"
    assert result.is_retryable is True


def test_diagnose_truncation_thinking_budget_exhausted():
    """Test thinking budget exhausted truncation diagnosis."""
    result = LLMErrorDiagnostic.diagnose_truncation("thinking_budget_exhausted", locale="en")

    assert result.error_type == "thinking_budget_exhausted"
    assert "reasoning" in result.user_message.lower()
    assert len(result.resolution_steps) > 0
    assert result.is_retryable is False
    assert result.locale == "en"


def test_diagnose_truncation_tool_call_truncated():
    """Test tool call truncated diagnosis."""
    result = LLMErrorDiagnostic.diagnose_truncation("tool_call_truncated", locale="en")

    assert result.error_type == "tool_call_truncated"
    assert "tool" in result.user_message.lower() or "incomplete" in result.user_message.lower()
    assert len(result.resolution_steps) > 0
    assert result.is_retryable is False
    assert result.locale == "en"


def test_diagnose_truncation_zh():
    """Test truncation diagnosis in Chinese."""
    result = LLMErrorDiagnostic.diagnose_truncation("thinking_budget_exhausted", locale="zh-CN")

    assert result.error_type == "thinking_budget_exhausted"
    assert "推理" in result.user_message or "token" in result.user_message
    assert result.locale == "zh-CN"


def test_diagnose_truncation_tool_call_zh():
    """Test tool call truncation in Chinese."""
    result = LLMErrorDiagnostic.diagnose_truncation("tool_call_truncated", locale="zh-CN")

    assert result.error_type == "tool_call_truncated"
    assert "工具" in result.user_message or "不完整" in result.user_message
    assert result.locale == "zh-CN"


def test_status_code_boundary_no_false_positive():
    """HTTP 状态码不应因端口号子串而误判"""
    # port 4023 不应被误判为 billing (402)
    r1 = LLMErrorDiagnostic.diagnose(Exception("port 4023 is unavailable"))
    assert r1.error_type != "billing"

    # port 4011 不应被误判为 api_key (401)
    r2 = LLMErrorDiagnostic.diagnose(Exception("Error on port 4011"))
    assert r2.error_type != "api_key"

    # port 4290 不应被误判为 rate_limit (429)
    r3 = LLMErrorDiagnostic.diagnose(Exception("listening on port 4290"))
    assert r3.error_type != "rate_limit"


def test_billing_with_cooldown_hint():
    """billing 诊断应包含 cooldown 提示"""
    exc = Exception("You exceeded your current quota (402)")
    result = LLMErrorDiagnostic.diagnose(exc, cooldown_remaining_ms=5000)

    assert result.error_type == "billing"
    assert "5" in result.user_message


class TestGetRecoveryActions:
    """Tests for LLMErrorDiagnostic.get_recovery_actions()."""

    def test_api_key_returns_update_action(self):
        actions = LLMErrorDiagnostic.get_recovery_actions("api_key")
        assert len(actions) == 1
        assert actions[0]["id"] == "update_key"
        assert actions[0]["url"] == "/settings"
        assert actions[0]["label"] == "Update API Key"

    def test_billing_returns_top_up_action(self):
        actions = LLMErrorDiagnostic.get_recovery_actions("billing")
        assert len(actions) == 1
        assert actions[0]["id"] == "top_up"
        assert actions[0]["url"] == "/settings"

    def test_model_returns_change_model_action(self):
        actions = LLMErrorDiagnostic.get_recovery_actions("model")
        assert len(actions) == 1
        assert actions[0]["id"] == "change_model"

    def test_custom_model_not_found_returns_change_model(self):
        actions = LLMErrorDiagnostic.get_recovery_actions("custom_model_not_found")
        assert len(actions) == 1
        assert actions[0]["id"] == "change_model"

    def test_unknown_error_returns_empty(self):
        assert LLMErrorDiagnostic.get_recovery_actions("unknown") == []

    def test_connection_error_returns_empty(self):
        assert LLMErrorDiagnostic.get_recovery_actions("connection") == []

    def test_rate_limit_returns_empty(self):
        assert LLMErrorDiagnostic.get_recovery_actions("rate_limit") == []

    def test_chinese_locale(self):
        actions = LLMErrorDiagnostic.get_recovery_actions("api_key", locale="zh-CN")
        assert actions[0]["label"] == "更新 API 密钥"

    def test_japanese_locale(self):
        actions = LLMErrorDiagnostic.get_recovery_actions("billing", locale="ja")
        assert actions[0]["label"] == "残高をチャージ"

    def test_korean_locale(self):
        actions = LLMErrorDiagnostic.get_recovery_actions("model", locale="ko")
        assert actions[0]["label"] == "모델 변경"

    def test_german_locale(self):
        actions = LLMErrorDiagnostic.get_recovery_actions("api_key", locale="de")
        assert actions[0]["label"] == "API-Schlüssel aktualisieren"

    def test_unsupported_locale_falls_back_to_english(self):
        actions = LLMErrorDiagnostic.get_recovery_actions("api_key", locale="fr")
        assert actions[0]["label"] == "Update API Key"

    def test_locale_prefix_fallback_zh_to_zh_cn(self):
        actions = LLMErrorDiagnostic.get_recovery_actions("api_key", locale="zh")
        assert actions[0]["label"] == "更新 API 密钥"

    def test_locale_prefix_fallback_zh_tw_to_zh_cn(self):
        actions = LLMErrorDiagnostic.get_recovery_actions("billing", locale="zh_TW")
        assert actions[0]["label"] == "充值余额"
