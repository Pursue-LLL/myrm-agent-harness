"""Agent configuration package — unified export of all config types and utilities.

子模块：
- llm: LLM 与 Agent 配置（LLMConfig, AgentConfig, StorageConfig）
- llm_safety: Provider Safety 包装器（normalize_messages, wrap_chat_model_with_safety）
- parsers: LiteLLM模型名解析和转换（to_litellm_model, parse_litellm_model）
- file_io: 文件 I/O 资源限制与正则安全配置（FileIOConfig）
- validator: 配置健康检查（ConfigIssue, check_config_health）
- presets: 配置预设（ConfigPreset, BUILTIN_PRESETS）
- readiness: 配置完整性检查（ConfigReadinessChecker, ConfigReadinessResult）
- exceptions: 配置异常定义（ConfigIncompleteError, InvalidConfigError）
"""

__all__ = [
    "BUILTIN_PRESETS",
    "DEFAULT_FILE_IO_CONFIG",
    "AgentConfig",
    "ConfigIncompleteError",
    "ConfigIssue",
    "ConfigPreset",
    "ConfigReadinessChecker",
    "ConfigReadinessResult",
    "ConfigValidationError",
    "FileIOConfig",
    "InvalidConfigError",
    "LLMConfig",
    "StorageConfig",
    "check_config_health",
    "normalize_messages",
    "parse_litellm_model",
    "to_litellm_model",
    "wrap_chat_model_with_safety",
]

_LAZY_IMPORTS = {
    "ConfigIncompleteError": ("myrm_agent_harness.agent.config.exceptions", "ConfigIncompleteError"),
    "ConfigValidationError": ("myrm_agent_harness.agent.config.exceptions", "ConfigValidationError"),
    "InvalidConfigError": ("myrm_agent_harness.agent.config.exceptions", "InvalidConfigError"),
    "DEFAULT_FILE_IO_CONFIG": ("myrm_agent_harness.agent.config.file_io", "DEFAULT_FILE_IO_CONFIG"),
    "FileIOConfig": ("myrm_agent_harness.agent.config.file_io", "FileIOConfig"),
    "AgentConfig": ("myrm_agent_harness.agent.config.llm", "AgentConfig"),
    "LLMConfig": ("myrm_agent_harness.agent.config.llm", "LLMConfig"),
    "StorageConfig": ("myrm_agent_harness.agent.config.llm", "StorageConfig"),
    "normalize_messages": ("myrm_agent_harness.agent.config.llm_safety", "normalize_messages"),
    "wrap_chat_model_with_safety": ("myrm_agent_harness.agent.config.llm_safety", "wrap_chat_model_with_safety"),
    "parse_litellm_model": ("myrm_agent_harness.agent.config.parsers", "parse_litellm_model"),
    "to_litellm_model": ("myrm_agent_harness.agent.config.parsers", "to_litellm_model"),
    "BUILTIN_PRESETS": ("myrm_agent_harness.agent.config.presets", "BUILTIN_PRESETS"),
    "ConfigPreset": ("myrm_agent_harness.agent.config.presets", "ConfigPreset"),
    "ConfigReadinessChecker": ("myrm_agent_harness.agent.config.readiness", "ConfigReadinessChecker"),
    "ConfigReadinessResult": ("myrm_agent_harness.agent.config.readiness", "ConfigReadinessResult"),
    "ConfigIssue": ("myrm_agent_harness.agent.config.validator", "ConfigIssue"),
    "check_config_health": ("myrm_agent_harness.agent.config.validator", "check_config_health"),
}

if __debug__:
    _lazy_set = set(_LAZY_IMPORTS.keys())
    _all_set = set(__all__)
    _extra = _lazy_set - _all_set
    if _extra:
        raise RuntimeError(f"agent.config: _LAZY_IMPORTS has symbols not in __all__: {_extra}")


def __getattr__(name: str):
    """Lazy load agent.config components on first access."""
    if name in _LAZY_IMPORTS:
        from importlib import import_module

        module_path, attr_name = _LAZY_IMPORTS[name]
        module = import_module(module_path)
        value = getattr(module, attr_name)
        globals()[name] = value
        return value

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
