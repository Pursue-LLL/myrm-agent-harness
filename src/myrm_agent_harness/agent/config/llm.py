"""LLM 与 Agent 配置。

提供统一的 LLM 配置接口，支持多种 LLM 提供商（OpenAI, Anthropic, Azure 等）。

CustomModelDef 和 LLMConfig 定义在 ``core.config.llm``（Single Source of Truth），
本模块 re-export 以保持 ``agent.config`` 公共 API 不变。
StorageConfig, TracingConfig, AgentConfig 为 agent 层特有配置。

[INPUT]
core.config.llm::CustomModelDef (POS: Custom model definition for self-hosted endpoints.)
core.config.llm::LLMConfig (POS: LLM configuration — framework-agnostic model config.)

[OUTPUT]
- CustomModelDef: re-export from core.config.llm
- LLMConfig: re-export from core.config.llm
- AgentConfig: Agent 运行时配置（Pydantic BaseModel，带字段验证和冲突检测）
- StorageConfig: 文件存储配置（dataclass）
- TracingConfig: 可视化追踪配置（dataclass）

[POS]
Agent configuration layer. Re-exports LLMConfig from core and defines agent-specific
config types (AgentConfig, StorageConfig, TracingConfig) with strict Pydantic field validation.

"""

import os
from dataclasses import dataclass

from pydantic import BaseModel, Field, field_validator, model_validator

from myrm_agent_harness.core.config.llm import CustomModelDef, LLMConfig


@dataclass
class StorageConfig:
    """存储配置

    支持配置不同的存储后端。

    Example:
        >>> # 本地存储
        >>> config = StorageConfig(backend_type="local", root_dir="./workspace")
        >>>
        >>> # 业务存储（需在业务项目中实现）
        >>> config = StorageConfig(backend_type="custom", custom_params={"endpoint": "..."})
    """

    backend_type: str = "local"  # 后端类型：local, custom
    root_dir: str = "./workspace"  # 本地存储根目录
    virtual_mode: bool = True  # 虚拟模式（沙箱化）
    custom_params: dict[str, object] | None = None


@dataclass
class TracingConfig:
    """可视化追踪配置 (Tracing)

    支持本地开源可视化 (Arize Phoenix) 和商业云端 (LangSmith)。
    注意：为了保证数据隐私，默认推荐使用本地 Phoenix。
    """

    enable_local_ui: bool = False  # 是否启用本地 Phoenix UI (需安装 [observability] 依赖)
    enable_langsmith: bool = False  # 是否启用 LangSmith (需配置 LANGCHAIN_TRACING_V2 等环境变量)
    phoenix_project_name: str = "myrm-agent"  # Phoenix 项目名称


class AgentConfig(BaseModel):
    """Agent 配置（支持后端路由）

    主构造函数为纯参数，from_env() 提供便捷的环境变量初始化。
    使用 Pydantic 进行严格字段验证，避免运行时错误。

    Example:
        >>> from myrm_agent_harness.backends.skills import CompositeSkillBackend, SkillBackend
        >>> from myrm_agent_harness.toolkits.storage import StorageProvider
        >>> from myrm_agent_harness.agent.skills.mcp import MCPConfig
        >>> from myrm_agent_harness.toolkits.code_execution import ExecutionConfig, ExecutionMode
        >>>
        >>> config = AgentConfig(
        ...     llm=LLMConfig(model="gpt-4", api_key="sk-..."),
        ...     skill_backend=CompositeSkillBackend(
        ...         routes={
        ...             "/user/": SkillBackend.local("./user_skills"),
        ...             "/system/": SkillBackend.storage(storage_backend),
        ...         }
        ...     ),
        ...     mcp_configs=[MCPConfig(...)],
        ...     storage_config=StorageConfig(backend_type="local", root_dir="./workspace"),
        ...     code_execution_config=ExecutionConfig(mode=ExecutionMode.LOCAL),
        ... )
    """

    # LLM 配置（必需）
    llm: LLMConfig = Field(..., description="LLM configuration")

    # 技能后端（可选）
    skill_backend: object | None = Field(default=None, description="Skill backend for loading skills")

    # MCP 配置（可选）
    mcp_configs: list[object] | None = Field(default=None, description="MCP server configurations")

    # 存储配置（可选）
    storage_config: StorageConfig | None = Field(default=None, description="Storage backend configuration")

    # 可视化追踪配置（可选）
    tracing_config: TracingConfig | None = Field(default=None, description="Tracing and UI configuration")

    # 代码执行配置（可选）
    code_execution_config: object | None = Field(default=None, description="Code execution sandbox configuration")

    # Agent 配置
    system_prompt: str | None = Field(default=None, description="Custom system prompt")
    recursion_limit: int = Field(default=50, description="Maximum recursion depth", ge=1, le=1000)
    timeout_seconds: int | None = Field(default=None, description="Global timeout in seconds", gt=0)
    parallel_tool_calls: bool | None = Field(
        default=None, description="Enable parallel tool calls (None=use LLM default)"
    )
    locale: str | None = Field(
        default=None,
        description="Locale for error messages and diagnostics (e.g., 'en', 'zh-CN'). None=auto-detect from environment",
    )

    # 工件配置
    enable_artifacts: bool = Field(default=True, description="Enable artifact generation")
    artifacts_output_path: str | None = Field(default=None, description="Output path for generated artifacts")

    # Planner 子智能体配置（可选）
    planner_config: object | None = Field(default=None, description="Planner subagent configuration")
    planner_llm_config: LLMConfig | None = Field(
        default=None,
        description="Dedicated LLM config for planner (optional, defaults to main LLM)",
    )

    # Vision Fallback 配置（可选）
    vision_fallback_llm: LLMConfig | None = Field(
        default=None,
        description="Vision fallback model (optional) for converting images to text when main model lacks vision",
    )

    model_config = {
        "arbitrary_types_allowed": True,  # Allow SkillBackend, ExecutionConfig, etc.
    }

    @field_validator("system_prompt")
    @classmethod
    def validate_system_prompt(cls, v: str | None) -> str | None:
        """Validate system_prompt is not empty and not too large."""
        if v is not None:
            if not v.strip():
                raise ValueError("system_prompt cannot be empty string")
            if len(v) > 100_000:
                raise ValueError(f"system_prompt too large: {len(v)} > 100000 characters")
        return v

    @model_validator(mode="after")
    def validate_config_consistency(self) -> "AgentConfig":
        """Validate configuration consistency (detect conflicting settings).

        Note: enable_artifacts=True without artifacts_output_path is allowed
        (framework may use default path), but will trigger a warning in health check.
        """
        return self

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "AgentConfig":
        """从字典显式构造配置（业务层调用）

        Args:
            data: 配置字典

        Returns:
            验证后的 AgentConfig 实例

        Example:
            config = AgentConfig.from_dict({
                "llm": {"model": "gpt-4", "api_key": "sk-..."},
                "recursion_limit": 100
            })
        """
        return cls.model_validate(data)

    @classmethod
    def from_preset(cls, name: str, llm: LLMConfig, **overrides) -> "AgentConfig":
        """从预设创建配置（业务层调用）

        Args:
            name: 预设名称（development, production, saas）
            llm: LLM 配置（业务层提供）
            **overrides: 覆盖预设的字段

        Returns:
            基于预设的 AgentConfig 实例

        Example:
            llm = LLMConfig(model="gpt-4", api_key="sk-...")
            config = AgentConfig.from_preset("development", llm, recursion_limit=300)

        Raises:
            ValueError: 未知的预设名称
        """
        from .presets import BUILTIN_PRESETS

        if name not in BUILTIN_PRESETS:
            available = ", ".join(BUILTIN_PRESETS.keys())
            raise ValueError(f"Unknown preset: {name}. Available: {available}")

        preset = BUILTIN_PRESETS[name]
        config_dict = {**preset.config_dict, "llm": llm, **overrides}
        return cls.from_dict(config_dict)

    @classmethod
    def from_env(cls) -> "AgentConfig":
        """从 MYRM_* 环境变量加载配置。"""
        llm_config = LLMConfig.from_env()

        storage_config = StorageConfig(
            backend_type=os.getenv("MYRM_STORAGE_BACKEND", "local"),
            root_dir=os.getenv("MYRM_WORKSPACE_PATH", "./workspace"),
            virtual_mode=os.getenv("MYRM_STORAGE_VIRTUAL_MODE", "true").lower() == "true",
        )

        tracing_config = TracingConfig(
            enable_local_ui=os.getenv("MYRM_ENABLE_LOCAL_UI", "false").lower() == "true",
            enable_langsmith=os.getenv("LANGCHAIN_TRACING_V2", "false").lower() == "true",
            phoenix_project_name=os.getenv("MYRM_PHOENIX_PROJECT", "myrm-agent"),
        )

        ptc_env = os.getenv("MYRM_PARALLEL_TOOL_CALLS")
        parallel_tool_calls: bool | None = None
        if ptc_env is not None:
            parallel_tool_calls = ptc_env.lower() == "true"

        return cls(
            llm=llm_config,
            storage_config=storage_config,
            tracing_config=tracing_config,
            recursion_limit=int(os.getenv("MYRM_RECURSION_LIMIT", "50")),
            timeout_seconds=(int(ts) if (ts := os.getenv("MYRM_TIMEOUT_SECONDS")) else None),
            parallel_tool_calls=parallel_tool_calls,
            enable_artifacts=os.getenv("MYRM_ENABLE_ARTIFACTS", "true").lower() == "true",
        )


__all__ = [
    "AgentConfig",
    "CustomModelDef",
    "LLMConfig",
    "StorageConfig",
    "TracingConfig",
]
