"""Cost Calculator

1. 本文件的 INPUT/OUTPUT/POS 注释

[INPUT]
- typing (POS: Python类型标准库)

[OUTPUT]
- LLMPricingConfig: LLM定价配置
- CostCalculator: 成本计算器

[POS]
LLM cost calculator (framework layer). Auto-calculates LLM invocation costs based on pricing tables.

"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar


@dataclass
class LLMPricingConfig:
    """LLM定价配置

    定义不同LLM模型的输入/输出token定价(美元/百万token)。
    默认提供主流模型定价,业务层可以自定义覆盖。
    """

    # 默认定价表(美元/百万token)- 2024年实际价格
    DEFAULT_PRICING: ClassVar[dict[str, dict[str, float]]] = {
        # OpenAI
        "gpt-4-turbo": {"prompt": 10.0, "completion": 30.0},
        "gpt-4o": {"prompt": 5.0, "completion": 15.0},
        "gpt-4": {"prompt": 30.0, "completion": 60.0},
        "gpt-3.5-turbo": {"prompt": 0.5, "completion": 1.5},
        # Anthropic
        "claude-3.5-sonnet": {"prompt": 3.0, "completion": 15.0},
        "claude-3-opus": {"prompt": 15.0, "completion": 75.0},
        "claude-3-sonnet": {"prompt": 3.0, "completion": 15.0},
        "claude-3-haiku": {"prompt": 0.25, "completion": 1.25},
        # DeepSeek
        "deepseek-chat": {"prompt": 0.14, "completion": 0.28},
        "deepseek-coder": {"prompt": 0.14, "completion": 0.28},
        # 其他
        "gemini-1.5-pro": {"prompt": 1.25, "completion": 5.0},
        "gemini-1.5-flash": {"prompt": 0.075, "completion": 0.3},
    }

    # 自定义定价表(可选)
    custom_pricing: dict[str, dict[str, float]] | None = None

    def get_prompt_price(self, model: str) -> float:
        """获取输入token价格(美元/百万token)

        Args:
            model: 模型名称

        Returns:
            输入token价格
        """
        pricing = (self.custom_pricing or {}).get(model) or self.DEFAULT_PRICING.get(model)
        if not pricing:
            raise ValueError(f"Unknown model: {model}. Please add to pricing config.")
        return pricing["prompt"]

    def get_completion_price(self, model: str) -> float:
        """获取输出token价格(美元/百万token)

        Args:
            model: 模型名称

        Returns:
            输出token价格
        """
        pricing = (self.custom_pricing or {}).get(model) or self.DEFAULT_PRICING.get(model)
        if not pricing:
            raise ValueError(f"Unknown model: {model}. Please add to pricing config.")
        return pricing["completion"]


class CostCalculator:
    """成本计算器

    基于LLM定价表自动计算调用成本。
    """

    def __init__(self, pricing_config: LLMPricingConfig | None = None):
        """初始化成本计算器

        Args:
            pricing_config: 定价配置(默认使用内置定价表)
        """
        self.pricing_config = pricing_config or LLMPricingConfig()

    def calculate_cost(self, model: str, prompt_tokens: int, completion_tokens: int) -> float:
        """计算LLM调用成本

        Args:
            model: 模型名称
            prompt_tokens: 输入token数
            completion_tokens: 输出token数

        Returns:
            成本(美元)

        Examples:
            >>> calc = CostCalculator()
            >>> calc.calculate_cost("gpt-4-turbo", 1000, 500)
            0.025  # (1000 * 10 + 500 * 30) / 1,000,000
        """
        prompt_price = self.pricing_config.get_prompt_price(model)
        completion_price = self.pricing_config.get_completion_price(model)

        cost_usd = (prompt_tokens * prompt_price + completion_tokens * completion_price) / 1_000_000

        return cost_usd

    def calculate_batch_cost(self, model: str, total_prompt_tokens: int, total_completion_tokens: int) -> float:
        """计算批量LLM调用的总成本

        Args:
            model: 模型名称
            total_prompt_tokens: 总输入token数
            total_completion_tokens: 总输出token数

        Returns:
            总成本(美元)
        """
        return self.calculate_cost(model, total_prompt_tokens, total_completion_tokens)

    def estimate_cost_per_optimization(
        self, model: str, avg_prompt_tokens: int = 2000, avg_completion_tokens: int = 1000
    ) -> float:
        """估算单次优化的平均成本

        Args:
            model: 模型名称
            avg_prompt_tokens: 平均输入token数(默认2000)
            avg_completion_tokens: 平均输出token数(默认1000)

        Returns:
            估算成本(美元)
        """
        return self.calculate_cost(model, avg_prompt_tokens, avg_completion_tokens)


def load_pricing_from_yaml(yaml_path: str) -> LLMPricingConfig:
    """从YAML文件加载自定义定价配置

    Args:
        yaml_path: YAML配置文件路径

    Returns:
        LLMPricingConfig实例

    Example YAML:
        gpt-4-turbo:
          prompt: 10.0
          completion: 30.0
        custom-model:
          prompt: 5.0
          completion: 15.0
    """
    from pathlib import Path

    import yaml

    path = Path(yaml_path)
    if not path.exists():
        return LLMPricingConfig()

    with open(path, encoding="utf-8") as f:
        custom_pricing = yaml.safe_load(f) or {}

    return LLMPricingConfig(custom_pricing=custom_pricing)
