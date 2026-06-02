"""示例: 自定义ProgressCalculator实现

[OUTPUT]
- WeightedTaskProgressCalculator: 基于任务类型/复杂度的加权进度计算器

[POS]
Custom ProgressCalculator reference implementation. Demonstrates weighted-task and time-based progress calculation.

"""

from __future__ import annotations


class WeightedTaskProgressCalculator:
    """加权任务进度计算器

    根据任务类型和复杂度,使用不同的权重计算进度。
    适用于不同任务类型耗时差异较大的场景。

    示例:
        >>> calculator = WeightedTaskProgressCalculator(
        ...     task_type="research",  # research任务通常更耗时
        ...     complexity_weight=1.5,  # 复杂度权重1.5x
        ... )
        >>> progress_data = calculator.calculate_progress(
        ...     current_tokens=5000,
        ...     budget_tokens=10000,
        ...     tool_count=3,
        ...     elapsed_seconds=60,
        ... )
        >>> print(progress_data["progress"])  # 0.5 * 1.5 = 0.75 (加权后)
    """

    def __init__(self, task_type: str = "default", complexity_weight: float = 1.0) -> None:
        """初始化加权进度计算器

        Args:
            task_type: 任务类型 (research/coding/review/planning等)
            complexity_weight: 复杂度权重 (1.0=标准, >1.0=更复杂, <1.0=更简单)
        """
        self.task_type = task_type
        self.complexity_weight = complexity_weight

        # 不同任务类型的token消耗速率估计 (tokens/second)
        self.task_type_rates = {
            "research": 50,  # 研究任务: 慢速 (需要深度思考)
            "coding": 100,  # 编码任务: 中速
            "review": 150,  # 审查任务: 快速 (主要阅读)
            "planning": 80,  # 规划任务: 中慢速
            "default": 100,  # 默认: 中速
        }

    def calculate_progress(
        self, current_tokens: int, budget_tokens: int | None, tool_count: int, elapsed_seconds: float
    ) -> dict[str, object]:
        """计算加权进度

        Args:
            current_tokens: 当前已消耗token数
            budget_tokens: 预算token数 (如果有)
            tool_count: 已调用工具数
            elapsed_seconds: 已耗时(秒)

        Returns:
            进度数据字典,包含:
            - progress: 进度 (0.0-1.0)
            - current_tokens: 当前token数
            - budget_tokens: 预算token数
            - tool_count: 工具调用数
            - is_estimated: 是否估计值
            - current_step: 当前步骤
            - eta_seconds: 预计剩余时间(秒)
            - eta_readable: 可读的预计剩余时间
            - task_type: 任务类型
            - complexity_weight: 复杂度权重
        """
        # 1. 基础进度计算
        if budget_tokens:
            base_progress = min(1.0, current_tokens / budget_tokens)
            is_estimated = False
        else:
            # 基于工具调用数估算 (假设平均需要8个工具调用)
            base_progress = min(1.0, tool_count / 8.0)
            is_estimated = True

        # 2. 应用复杂度权重
        # 注意: 复杂度越高,相同token消耗下进度越低
        weighted_progress = min(1.0, base_progress * self.complexity_weight)

        # 3. ETA估算
        eta_seconds = None
        eta_readable = None

        if budget_tokens and elapsed_seconds > 0:
            # 获取任务类型对应的估计token消耗速率
            estimated_rate = self.task_type_rates.get(self.task_type, 100)

            # 实际速率 (考虑已消耗时间)
            actual_rate = current_tokens / elapsed_seconds if elapsed_seconds > 0 else estimated_rate

            # 混合估计速率和实际速率 (70%实际 + 30%估计)
            blended_rate = actual_rate * 0.7 + estimated_rate * 0.3

            # 计算剩余token和预计时间
            remaining_tokens = budget_tokens - current_tokens
            if remaining_tokens > 0 and blended_rate > 0:
                # 考虑复杂度权重 (复杂度越高,预计时间越长)
                eta_seconds = int((remaining_tokens / blended_rate) * self.complexity_weight)

                # 格式化为可读字符串
                if eta_seconds > 60:
                    mins = eta_seconds // 60
                    secs = eta_seconds % 60
                    eta_readable = f"{mins}m{secs}s"
                else:
                    eta_readable = f"{eta_seconds}s"

        # 4. 构建进度数据
        progress_data = {
            "progress": weighted_progress,
            "current_tokens": current_tokens,
            "budget_tokens": budget_tokens,
            "tool_count": tool_count,
            "is_estimated": is_estimated,
            "current_step": f"{self.task_type} task",
            "task_type": self.task_type,
            "complexity_weight": self.complexity_weight,
        }

        if eta_seconds is not None:
            progress_data["eta_seconds"] = eta_seconds
            progress_data["eta_readable"] = eta_readable

        return progress_data


class TimeBasedProgressCalculator:
    """基于时间的进度计算器

    适用于已知任务预计耗时的场景。

    示例:
        >>> calculator = TimeBasedProgressCalculator(
        ...     estimated_duration_seconds=300,  # 预计5分钟
        ... )
        >>> progress_data = calculator.calculate_progress(
        ...     current_tokens=0,
        ...     budget_tokens=None,
        ...     tool_count=0,
        ...     elapsed_seconds=150,  # 已经过2.5分钟
        ... )
        >>> print(progress_data["progress"])  # 0.5 (50%)
    """

    def __init__(self, estimated_duration_seconds: float) -> None:
        """初始化时间进度计算器

        Args:
            estimated_duration_seconds: 预计任务总耗时(秒)
        """
        self.estimated_duration_seconds = estimated_duration_seconds

    def calculate_progress(
        self, current_tokens: int, budget_tokens: int | None, tool_count: int, elapsed_seconds: float
    ) -> dict[str, object]:
        """基于时间计算进度

        Args:
            current_tokens: 当前已消耗token数 (未使用)
            budget_tokens: 预算token数 (未使用)
            tool_count: 已调用工具数 (未使用)
            elapsed_seconds: 已耗时(秒)

        Returns:
            进度数据字典
        """
        # 基于时间计算进度
        progress = min(1.0, elapsed_seconds / self.estimated_duration_seconds)

        # 计算ETA
        eta_seconds = None
        eta_readable = None
        if progress < 1.0:
            eta_seconds = int(self.estimated_duration_seconds - elapsed_seconds)
            if eta_seconds > 60:
                mins = eta_seconds // 60
                secs = eta_seconds % 60
                eta_readable = f"{mins}m{secs}s"
            else:
                eta_readable = f"{eta_seconds}s"

        progress_data = {
            "progress": progress,
            "current_tokens": current_tokens,
            "budget_tokens": budget_tokens,
            "tool_count": tool_count,
            "is_estimated": True,
            "current_step": f"elapsed {int(elapsed_seconds)}s / {int(self.estimated_duration_seconds)}s",
            "calculation_method": "time-based",
        }

        if eta_seconds is not None:
            progress_data["eta_seconds"] = eta_seconds
            progress_data["eta_readable"] = eta_readable

        return progress_data
