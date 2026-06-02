"""增强配置健康检查测试"""

from myrm_agent_harness.agent.config import AgentConfig, LLMConfig, StorageConfig, check_config_health


def test_storage_config_invalid_backend_type():
    """测试 storage_config.backend_type 不合法"""
    llm = LLMConfig(model="gpt-4", api_key="test-key")
    storage = StorageConfig(backend_type="invalid_backend")
    config = AgentConfig(llm=llm, storage_config=storage, enable_artifacts=False)

    issues = check_config_health(config)

    assert len(issues) == 1
    assert issues[0].level == "error"
    assert "backend_type" in issues[0].message.lower()
    assert issues[0].field == "storage_config.backend_type"


def test_storage_config_empty_root_dir():
    """测试 storage_config.root_dir 为空"""
    llm = LLMConfig(model="gpt-4", api_key="test-key")
    storage = StorageConfig(backend_type="local", root_dir="")
    config = AgentConfig(llm=llm, storage_config=storage, enable_artifacts=False)

    issues = check_config_health(config)

    assert len(issues) == 1
    assert issues[0].level == "error"
    assert "root_dir" in issues[0].message.lower()
    assert issues[0].field == "storage_config.root_dir"


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


def test_valid_storage_config():
    """测试有效的 storage_config"""
    llm = LLMConfig(model="gpt-4", api_key="test-key")
    storage = StorageConfig(backend_type="local", root_dir="./workspace")
    config = AgentConfig(llm=llm, storage_config=storage, enable_artifacts=False)

    issues = check_config_health(config)

    # 可能有其他警告，但不应该有 storage_config 相关的错误
    storage_issues = [i for i in issues if "storage_config" in (i.field or "")]
    assert len(storage_issues) == 0


def test_multiple_new_issues():
    """测试多个新增检查项同时触发"""
    llm = LLMConfig(model="gpt-4", api_key="test-key")
    storage = StorageConfig(backend_type="invalid", root_dir="")
    planner_llm = LLMConfig(model="gpt-3.5-turbo", api_key="test-key")
    config = AgentConfig(
        llm=llm, storage_config=storage, planner_llm_config=planner_llm, planner_config=None, enable_artifacts=False
    )

    issues = check_config_health(config)

    # 应该有 3 个新增的问题
    assert len(issues) == 3
    error_count = sum(1 for i in issues if i.level == "error")
    warning_count = sum(1 for i in issues if i.level == "warning")
    assert error_count == 2  # storage backend + root_dir
    assert warning_count == 1  # planner config
