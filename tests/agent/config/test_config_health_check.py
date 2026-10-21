"""配置健康检查测试"""

from myrm_agent_harness.agent.config import AgentConfig, LLMConfig, check_config_health


def test_no_issues_for_valid_config():
    """测试有效配置无问题"""
    llm = LLMConfig(model="gpt-4", api_key="test-key")
    config = AgentConfig(llm=llm, recursion_limit=100, enable_artifacts=False)

    issues = check_config_health(config)

    assert len(issues) == 0


def test_high_recursion_limit_warning():
    """测试高 recursion_limit 产生警告"""
    llm = LLMConfig(model="gpt-4", api_key="test-key")
    config = AgentConfig(llm=llm, recursion_limit=500, enable_artifacts=False)

    issues = check_config_health(config)

    assert len(issues) == 1
    assert issues[0].level == "warning"
    assert "recursion_limit" in issues[0].message.lower()
    assert issues[0].field == "recursion_limit"


def test_very_long_timeout_warning():
    """测试过长 timeout 产生警告"""
    llm = LLMConfig(model="gpt-4", api_key="test-key")
    config = AgentConfig(llm=llm, timeout_seconds=7200, enable_artifacts=False)

    issues = check_config_health(config)

    assert len(issues) == 1
    assert issues[0].level == "warning"
    assert "timeout" in issues[0].message.lower()
    assert issues[0].field == "timeout_seconds"


def test_high_temperature_info():
    """测试高 temperature 产生提示"""
    llm = LLMConfig(model="gpt-4", api_key="test-key", temperature=1.5)
    config = AgentConfig(llm=llm, enable_artifacts=False)

    issues = check_config_health(config)

    assert len(issues) == 1
    assert issues[0].level == "info"
    assert "temperature" in issues[0].message.lower()
    assert issues[0].field == "llm.temperature"


def test_large_system_prompt_warning():
    """测试过大 system_prompt 产生警告"""
    llm = LLMConfig(model="gpt-4", api_key="test-key")
    large_prompt = "x" * 60_000
    config = AgentConfig(llm=llm, system_prompt=large_prompt, enable_artifacts=False)

    issues = check_config_health(config)

    assert len(issues) == 1
    assert issues[0].level == "warning"
    assert "system_prompt" in issues[0].message.lower()
    assert issues[0].field == "system_prompt"


def test_multiple_issues():
    """测试多个问题同时检测"""
    llm = LLMConfig(model="gpt-4", api_key="test-key", temperature=1.5)
    config = AgentConfig(llm=llm, recursion_limit=800, timeout_seconds=7200, enable_artifacts=False)

    issues = check_config_health(config)

    assert len(issues) == 3
    levels = {issue.level for issue in issues}
    assert "warning" in levels
    assert "info" in levels


def test_issue_has_suggestion():
    """测试问题包含建议"""
    llm = LLMConfig(model="gpt-4", api_key="test-key")
    config = AgentConfig(llm=llm, recursion_limit=500, enable_artifacts=False)

    issues = check_config_health(config)

    assert len(issues) == 1
    assert issues[0].suggestion is not None
    assert len(issues[0].suggestion) > 0
