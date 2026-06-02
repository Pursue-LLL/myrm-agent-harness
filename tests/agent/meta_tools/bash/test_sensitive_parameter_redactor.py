"""Sensitive Parameter Redactor单元测试"""

from myrm_agent_harness.agent.meta_tools.bash.sensitive_parameter_redactor import SensitiveParameterRedactor


class TestSensitiveParameterRedactor:
    """测试敏感参数脱敏器"""

    def test_redact_token_eq(self):
        """测试脱敏 --token=value 形式"""
        redactor = SensitiveParameterRedactor()

        cmd = "curl --token=abc123 https://api.example.com"
        result = redactor.redact(cmd)
        assert "--token=***REDACTED***" in result
        assert "abc123" not in result

    def test_redact_api_key_eq(self):
        """测试脱敏 --api-key=value 形式"""
        redactor = SensitiveParameterRedactor()

        cmd = "cli --api-key=secret123 action"
        result = redactor.redact(cmd)
        assert "--api-key=***REDACTED***" in result
        assert "secret123" not in result

    def test_redact_password_eq(self):
        """测试脱敏 --password=value 形式"""
        redactor = SensitiveParameterRedactor()

        cmd = "mysql --password=mypass123 -u user"
        result = redactor.redact(cmd)
        assert "--password=***REDACTED***" in result
        assert "mypass123" not in result

    def test_redact_env_var(self):
        """测试脱敏环境变量 TOKEN=value 形式"""
        redactor = SensitiveParameterRedactor()

        cmd = "TOKEN=abc123 curl https://api.example.com"
        result = redactor.redact(cmd)
        assert "TOKEN=***REDACTED***" in result
        assert "abc123" not in result

    def test_redact_multiple_params(self):
        """测试脱敏多个敏感参数"""
        redactor = SensitiveParameterRedactor()

        cmd = "cli --api-key=key123 --token=token456 action"
        result = redactor.redact(cmd)
        assert "--api-key=***REDACTED***" in result
        assert "--token=***REDACTED***" in result
        assert "key123" not in result
        assert "token456" not in result

    def test_custom_keywords(self):
        """测试自定义敏感关键词"""
        redactor = SensitiveParameterRedactor(custom_keywords=["custom_secret"])

        cmd = "cli --custom_secret=value123 action"
        result = redactor.redact(cmd)
        assert "--custom_secret=***REDACTED***" in result
        assert "value123" not in result

    def test_no_sensitive_params(self):
        """测试无敏感参数的命令不变"""
        redactor = SensitiveParameterRedactor()

        cmd = "ls -la /tmp"
        result = redactor.redact(cmd)
        assert result == cmd

    def test_quoted_value(self):
        """测试引号包裹的值"""
        redactor = SensitiveParameterRedactor()

        cmd = 'curl --token="abc123" https://api.example.com'
        result = redactor.redact(cmd)
        assert "--token=***REDACTED***" in result
        assert "abc123" not in result

    def test_empty_command(self):
        """测试空命令"""
        redactor = SensitiveParameterRedactor()

        result = redactor.redact("")
        assert result == ""

    def test_case_insensitive(self):
        """测试大小写不敏感"""
        redactor = SensitiveParameterRedactor()

        cmd = "cli --TOKEN=abc123 --Password=pwd456 action"
        result = redactor.redact(cmd)
        assert "***REDACTED***" in result
        assert "abc123" not in result
        assert "pwd456" not in result
