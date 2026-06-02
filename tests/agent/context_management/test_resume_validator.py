"""Tests for ResumeValidator"""

from myrm_agent_harness.agent.context_management.infra.resume_validator import ResumeValidator


class TestResumeValidator:
    """Test ResumeValidator configuration consistency checks"""

    def test_validate_identical_configs(self):
        """配置完全一致时，返回空列表"""
        validator = ResumeValidator()
        checkpoint_config = {
            "agent_id": "agent-123",
            "system_prompt": "You are a helpful assistant",
            "tools": [{"name": "bash"}, {"name": "file_read"}],
        }
        current_config = checkpoint_config.copy()

        issues = validator.validate(checkpoint_config, current_config)
        assert issues == []

    def test_validate_agent_id_mismatch(self):
        """Agent ID不一致时，返回错误"""
        validator = ResumeValidator()
        checkpoint_config = {"agent_id": "agent-123"}
        current_config = {"agent_id": "agent-456"}

        issues = validator.validate(checkpoint_config, current_config)
        assert len(issues) == 1
        assert "agent_id_mismatch" in issues[0]

    def test_validate_system_prompt_changed(self):
        """System Prompt改变时，返回警告"""
        validator = ResumeValidator()
        checkpoint_config = {"system_prompt": "You are a helpful assistant"}
        current_config = {"system_prompt": "You are a coding assistant"}

        issues = validator.validate(checkpoint_config, current_config)
        assert len(issues) == 1
        assert "system_prompt_changed" in issues[0]

    def test_validate_tools_added(self):
        """Tools列表增加工具时，返回警告"""
        validator = ResumeValidator()
        checkpoint_config = {"tools": [{"name": "bash"}, {"name": "file_read"}]}
        current_config = {"tools": [{"name": "bash"}, {"name": "file_read"}, {"name": "web_search"}]}

        issues = validator.validate(checkpoint_config, current_config)
        assert len(issues) == 1
        assert "tools_changed" in issues[0]
        assert "+1" in issues[0]

    def test_validate_tools_removed(self):
        """Tools列表移除工具时，返回警告"""
        validator = ResumeValidator()
        checkpoint_config = {"tools": [{"name": "bash"}, {"name": "file_read"}, {"name": "web_search"}]}
        current_config = {"tools": [{"name": "bash"}, {"name": "file_read"}]}

        issues = validator.validate(checkpoint_config, current_config)
        assert len(issues) == 1
        assert "tools_changed" in issues[0]
        assert "-1" in issues[0]

    def test_validate_multiple_issues(self):
        """多个配置不一致时，返回所有问题"""
        validator = ResumeValidator()
        checkpoint_config = {
            "agent_id": "agent-123",
            "system_prompt": "You are a helpful assistant",
            "tools": [{"name": "bash"}],
        }
        current_config = {
            "agent_id": "agent-456",
            "system_prompt": "You are a coding assistant",
            "tools": [{"name": "bash"}, {"name": "file_read"}],
        }

        issues = validator.validate(checkpoint_config, current_config)
        assert len(issues) == 3
        assert any("agent_id_mismatch" in issue for issue in issues)
        assert any("system_prompt_changed" in issue for issue in issues)
        assert any("tools_changed" in issue for issue in issues)

    def test_validate_empty_configs(self):
        """空配置时，不报错"""
        validator = ResumeValidator()
        issues = validator.validate({}, {})
        assert issues == []

    def test_validate_missing_fields(self):
        """缺少字段时，不报错（向后兼容）"""
        validator = ResumeValidator()
        checkpoint_config = {"agent_id": "agent-123"}
        current_config = {}

        issues = validator.validate(checkpoint_config, current_config)
        assert issues == []

    def test_extract_tool_names_from_dict_list(self):
        """正确提取dict格式的tools名称"""
        validator = ResumeValidator()
        tools = [{"name": "bash"}, {"name": "file_read"}]
        names = validator._extract_tool_names(tools)
        assert names == {"bash", "file_read"}

    def test_extract_tool_names_from_object_list(self):
        """正确提取object格式的tools名称"""
        validator = ResumeValidator()

        class MockTool:
            def __init__(self, name: str):
                self.name = name

        tools = [MockTool("bash"), MockTool("file_read")]
        names = validator._extract_tool_names(tools)
        assert names == {"bash", "file_read"}

    def test_extract_tool_names_invalid_input(self):
        """无效输入时，返回空集合"""
        validator = ResumeValidator()
        assert validator._extract_tool_names(None) == set()
        assert validator._extract_tool_names("invalid") == set()
        assert validator._extract_tool_names([]) == set()

    def test_generate_diff_report_no_changes(self):
        """配置一致时，生成简单报告"""
        validator = ResumeValidator()
        checkpoint_config = {"agent_id": "agent-123"}
        current_config = {"agent_id": "agent-123"}

        report = validator.generate_diff_report(checkpoint_config, current_config)
        assert "[OK]" in report
        assert "no changes" in report

    def test_generate_diff_report_with_changes(self):
        """配置变化时，生成详细报告"""
        validator = ResumeValidator()
        checkpoint_config = {
            "agent_id": "agent-123",
            "system_prompt": "You are a helpful assistant",
            "tools": [{"name": "bash"}],
        }
        current_config = {
            "agent_id": "agent-456",
            "system_prompt": "You are a coding assistant with more features",
            "tools": [{"name": "bash"}, {"name": "file_read"}],
        }

        report = validator.generate_diff_report(checkpoint_config, current_config)
        assert "Agent ID" in report
        assert "agent-123" in report
        assert "agent-456" in report
        assert "System Prompt" in report
        assert "Tools" in report
        assert "Added" in report

    def test_calculate_similarity_identical(self):
        """相同文本相似度为100%"""
        validator = ResumeValidator()
        similarity = validator._calculate_similarity("hello world", "hello world")
        assert similarity == 100.0

    def test_calculate_similarity_different(self):
        """不同文本相似度低于100%"""
        validator = ResumeValidator()
        # 字符级比较：前5个字符不同，后6个相同(" world")
        similarity = validator._calculate_similarity("hello world", "goodbye world")
        assert 0 <= similarity < 100

    def test_calculate_similarity_empty(self):
        """空文本相似度为0%"""
        validator = ResumeValidator()
        assert validator._calculate_similarity("", "hello") == 0.0
        assert validator._calculate_similarity("hello", "") == 0.0
