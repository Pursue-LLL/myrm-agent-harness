"""增强配置健康检查测试"""

from myrm_agent_harness.agent.config import AgentConfig, LLMConfig, check_config_health


def test_planner_llm_without_planner_config():
    """测试 planner_llm_config 设置但 planner_config 为 None"""
    llm = LLMConfig(model="gpt-4", api_key="test-key")
    planner_llm = LLMConfig(model="gpt-3.5-turbo", api_key="test-key")
    config = AgentConfig(llm=llm, planner_llm_config=planner_llm, planner_config=None, enable_artifacts=False)

    issues = check_config_health(config)

    assert len(issues) == 1
    assert issues[0].level == "warning"
    assert "planner_llm_config" in issues[0].message.lower()
    assert "planner_config" in issues[0].message.lower()
    assert issues[0].field == "planner_config"
