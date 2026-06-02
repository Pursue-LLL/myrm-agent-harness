"""Skill Optimization Configuration

1. 本文件的 INPUT/OUTPUT/POS 注释

[INPUT]
- dataclasses.dataclass (POS: Python数据类装饰器)

[OUTPUT]
- OptimizationConfig: 优化总配置
- ABTestConfig: A/B测试配置
- SecurityConfig: 安全验证配置
- MonitoringConfig: 监控配置
- PerformanceConfig: 性能优化配置

[POS]
Skill optimization system configuration. Provides flexible config options for A/B testing, monitoring, performance tuning, and security.

"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SecurityConfig:
    """安全验证配置"""

    # 危险模式列表（正则表达式）
    dangerous_patterns: list[str] = field(
        default_factory=lambda: [
            r"rm\s+-rf",
            r"DROP\s+TABLE",
            r"eval\(",
            r"/etc/passwd",
            r"~/.ssh",
            r"__import__",
            r"exec\(",
            r"os\.system",
            r"subprocess\.",
        ]
    )

    # 是否启用沙箱验证（耗时但更安全）
    enable_sandbox_validation: bool = False

    # 沙箱验证超时（秒）
    sandbox_timeout: float = 10.0


@dataclass
class ABTestConfig:
    """A/B测试配置"""

    # 最小样本量
    min_sample_size: int = 50

    # 最大样本量
    max_sample_size: int = 500

    # 置信度（用于统计显著性检验）
    confidence_level: float = 0.95

    # 最小效果量（quality_score差异）
    min_effect_size: float = 0.05

    # 是否启用自适应采样（低频skill快速验证）
    enable_adaptive_sampling: bool = True

    # 是否启用快速失败检测
    enable_quick_failure_detection: bool = True

    # 快速失败阈值（candidate比baseline差多少就提前停止）
    quick_failure_threshold: float = 0.1

    # 是否启用早停（显著优于baseline时提前结束）
    enable_early_stopping: bool = True

    # 早停阈值（candidate比baseline好多少就提前结束）
    early_stopping_threshold: float = 0.15


@dataclass
class MonitoringConfig:
    """监控配置"""

    # 质量评估间隔（秒）
    evaluation_interval: float = 3600.0  # 1 hour

    # 优化触发阈值（quality_score低于此值触发优化）
    optimization_threshold: float = 0.6

    # 冷却期（同一skill两次优化的最小间隔，秒）
    cooldown_period: float = 86400.0  # 24 hours

    # 断路器阈值（连续失败多少次后禁用自动优化）
    circuit_breaker_threshold: int = 5

    # 断路器恢复时间（秒）
    circuit_breaker_recovery_time: float = 3600.0  # 1 hour


@dataclass
class PerformanceConfig:
    """性能优化配置"""

    # 是否启用Prompt缓存
    enable_prompt_cache: bool = True

    # Prompt缓存TTL（秒）
    prompt_cache_ttl: float = 3600.0

    # 是否启用评估结果缓存
    enable_evaluation_cache: bool = True

    # 评估结果缓存TTL（秒）
    evaluation_cache_ttl: float = 1800.0

    # 是否启用异步处理
    enable_async_processing: bool = True

    # LLM调用超时（秒）
    llm_timeout: float = 60.0

    # LLM调用最大重试次数
    llm_max_retries: int = 3

    # LLM调用重试延迟（秒，指数退避）
    llm_retry_delay: float = 2.0


@dataclass
class OptimizationConfig:
    """优化总配置"""

    # 安全验证配置
    security: SecurityConfig = field(default_factory=SecurityConfig)

    # A/B测试配置
    ab_test: ABTestConfig = field(default_factory=ABTestConfig)

    # 监控配置
    monitoring: MonitoringConfig = field(default_factory=MonitoringConfig)

    # 性能配置
    performance: PerformanceConfig = field(default_factory=PerformanceConfig)

    # 是否启用自动优化
    enable_auto_optimization: bool = True

    # 是否启用用户反馈收集
    enable_user_feedback: bool = True

    @classmethod
    def default(cls) -> OptimizationConfig:
        """默认配置（生产环境推荐）"""
        return cls()

    @classmethod
    def development(cls) -> OptimizationConfig:
        """开发环境配置（更快的反馈周期）"""
        return cls(
            monitoring=MonitoringConfig(
                evaluation_interval=300.0,  # 5 minutes
                cooldown_period=600.0,  # 10 minutes
            ),
            ab_test=ABTestConfig(min_sample_size=10, max_sample_size=50),
        )

    @classmethod
    def conservative(cls) -> OptimizationConfig:
        """保守配置（更严格的安全验证和测试）"""
        return cls(
            security=SecurityConfig(enable_sandbox_validation=True),
            ab_test=ABTestConfig(
                min_sample_size=100, max_sample_size=1000, confidence_level=0.99, enable_quick_failure_detection=False
            ),
            monitoring=MonitoringConfig(
                optimization_threshold=0.5,
                cooldown_period=172800.0,  # 48 hours
            ),
        )
