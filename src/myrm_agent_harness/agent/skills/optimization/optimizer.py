"""Skill Optimizer

1. 本文件的 INPUT/OUTPUT/POS 注释

[INPUT]
- .types::SkillType, SkillQualityScore, LockProvider, OptimizationResult (POS: 核心类型)
- .config::OptimizationConfig (POS: 优化配置)
- .security::SkillSecurityValidator (POS: 安全验证器)
- backends.skills.types::SkillMetadata (POS: Skill元数据)

[OUTPUT]
- SkillOptimizer: Skill优化器（5维评估 + 类型检测 + 分布式锁）

[POS]
Skill optimizer core engine. Orchestrates the full optimization pipeline: data collection, analysis, suggestion generation, and A/B validation.

"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

    from myrm_agent_harness.backends.skills.types import SkillMetadata

    from .config import OptimizationConfig
    from .security import SkillSecurityValidator
    from .types import LockProvider, OptimizationResult, SkillQualityScore, SkillType

from .observability import Timer, get_metrics_collector, structured_log
from .types import LockAcquisitionError, OptimizationError, OptimizationStatus, SecurityError

logger = logging.getLogger(__name__)
metrics = get_metrics_collector()


class SkillOptimizer:
    """Skill优化器

    核心功能：
    1. Skill类型检测：根据storage_path自动识别PREBUILT/USER/WORKSPACE
    2. 并发控制：Prebuilt skill使用分布式锁，User/Workspace skill不需要
    3. 5维质量评估：综合评估skill质量
    4. LLM优化：调用LLM生成优化后的skill
    5. 安全验证：多层防护确保生成的skill安全
    """

    def __init__(
        self,
        llm: BaseChatModel,
        config: OptimizationConfig,
        security_validator: SkillSecurityValidator,
        lock_provider: LockProvider | None = None,
    ):
        """初始化优化器

        Args:
            llm: LLM实例（用于生成优化后的skill）
            config: 优化配置
            security_validator: 安全验证器
            lock_provider: 分布式锁提供者（可选，仅Prebuilt skill需要）
        """
        self.llm = llm
        self.config = config
        self.security_validator = security_validator
        self.lock_provider = lock_provider

    def _detect_skill_type(self, skill: SkillMetadata) -> SkillType:
        """检测skill类型

        根据storage_path判断skill类型：
        - skills/prebuilt → PREBUILT
        - users/{user_id}/skills → USER
        - 其他 → WORKSPACE

        Args:
            skill: Skill元数据

        Returns:
            SkillType枚举
        """
        from .types import SkillType

        storage_path = skill.storage_path or ""

        if storage_path.startswith("skills/prebuilt"):
            return SkillType.PREBUILT
        elif "/users/" in storage_path or storage_path.startswith("users/"):
            return SkillType.USER
        else:
            return SkillType.WORKSPACE

    async def optimize_skill(
        self, skill: SkillMetadata, quality_score: SkillQualityScore, content: str | None = None
    ) -> OptimizationResult:
        """优化skill

        自动处理并发控制：
        - Prebuilt skill: 使用分布式锁
        - User/Workspace skill: 无需锁

        Args:
            skill: Skill元数据
            quality_score: 当前质量评分

        Returns:
            OptimizationResult: 优化结果

        Raises:
            OptimizationError: 优化失败
            SecurityError: 安全验证失败
        """

        skill_type = self._detect_skill_type(skill)
        started_at = datetime.now()

        structured_log(
            logger,
            "INFO",
            "Starting skill optimization",
            skill_id=skill.name,
            skill_type=skill_type.value,
            quality_score=quality_score.overall_score,
        )

        metrics.inc_counter("skill_optimizations_total", labels={"skill_type": skill_type.value})
        metrics.inc_gauge("skill_optimizations_active", labels={"skill_type": skill_type.value})

        try:
            # 根据skill类型决定是否需要锁
            from myrm_agent_harness.toolkits.storage.types import SkillType

            if skill_type == SkillType.PREBUILT:
                if not self.lock_provider:
                    raise OptimizationError("Prebuilt skill需要并发锁，但未提供lock_provider")

                # 使用跨进程锁 (Cross-Process Lock)
                try:
                    async with self.lock_provider.acquire(f"skill:opt:{skill.name}", timeout=30):
                        result = await self._do_optimize(skill, quality_score, skill_type, started_at, content=content)
                        metrics.inc_counter(
                            "skill_optimizations_success_total", labels={"skill_type": skill_type.value}
                        )
                        return result
                except LockAcquisitionError:
                    metrics.inc_counter(
                        "skill_optimizations_failed_total",
                        labels={"skill_type": skill_type.value, "reason": "lock_failure"},
                    )
                    raise OptimizationError(f"无法获取skill优化锁，可能另一个优化正在进行: {skill.name}") from None
            else:
                # User/Workspace skill不需要锁
                result = await self._do_optimize(skill, quality_score, skill_type, started_at, content=content)
                metrics.inc_counter("skill_optimizations_success_total", labels={"skill_type": skill_type.value})
                return result

        except (SecurityError, OptimizationError):
            metrics.inc_counter(
                "skill_optimizations_failed_total",
                labels={"skill_type": skill_type.value, "reason": "validation_error"},
            )
            raise
        except Exception as e:
            metrics.inc_counter(
                "skill_optimizations_failed_total", labels={"skill_type": skill_type.value, "reason": "unknown_error"}
            )
            logger.error(f"Skill optimization failed: {skill.name}, error: {e}")
            raise OptimizationError(f"Skill优化失败: {e!s}") from e
        finally:
            metrics.dec_gauge("skill_optimizations_active", labels={"skill_type": skill_type.value})

    async def _do_optimize(
        self,
        skill: SkillMetadata,
        quality_score: SkillQualityScore,
        skill_type: SkillType,
        started_at: datetime,
        content: str | None = None,
    ) -> OptimizationResult:
        """执行优化（内部方法）

        步骤：
        1. LLM生成优化后的skill
        2. 安全验证
        3. 语法验证
        4. 返回优化结果
        """
        from .types import OptimizationResult

        # 1. LLM生成优化后的skill（记录耗时）
        with Timer("skill_optimizations_duration_seconds", labels={"skill_type": skill_type.value}):
            optimized_content = await self._generate_optimized_skill(skill, quality_score, content=content)

        # 2. 安全验证
        security_result = self.security_validator.validate_skill(optimized_content)
        if not security_result.passed:
            raise SecurityError(f"安全验证失败: {', '.join(security_result.issues)}")

        # 3. 构建结果
        result = OptimizationResult(
            skill_id=skill.name,
            skill_type=skill_type,
            baseline_score=quality_score,
            optimized_content=optimized_content,
            security_validation=security_result,
            status=OptimizationStatus.COMPLETED,
            started_at=started_at,
            completed_at=datetime.now(),
        )

        duration = (result.completed_at - result.started_at).total_seconds()
        structured_log(
            logger,
            "INFO",
            "Skill optimization completed",
            skill_id=skill.name,
            duration_seconds=duration,
            quality_score_before=quality_score.overall_score,
        )

        return result

    async def _generate_optimized_skill(
        self, skill: SkillMetadata, quality_score: SkillQualityScore, content: str | None = None
    ) -> str:
        """LLM生成优化后的skill

        构建优化prompt，调用LLM生成改进版本。

        Args:
            skill: Skill元数据
            quality_score: 当前质量评分

        Returns:
            str: 优化后的skill内容（SKILL.md完整内容）
        """
        from langchain_core.messages import HumanMessage

        # 构建优化prompt
        prompt = self._build_optimization_prompt(skill, quality_score, content=content)

        # 带重试的LLM调用
        max_retries = self.config.performance.llm_max_retries
        retry_delay = self.config.performance.llm_retry_delay
        timeout = self.config.performance.llm_timeout

        for attempt in range(max_retries):
            try:
                # 调用LLM（记录metrics）
                import asyncio

                metrics.inc_counter("llm_calls_total", labels={"operation": "skill_optimization"})

                async with Timer("llm_calls_duration_seconds", labels={"operation": "skill_optimization"}):
                    response = await asyncio.wait_for(self.llm.ainvoke([HumanMessage(content=prompt)]), timeout=timeout)

                # 提取内容
                optimized_content = response.content if hasattr(response, "content") else str(response)

                # 验证Markdown格式
                if not optimized_content.startswith("---") or optimized_content.count("---") < 2:
                    raise OptimizationError("LLM生成的skill缺少YAML frontmatter")

                logger.info(f"LLM optimization succeeded for skill: {skill.name}")
                return optimized_content

            except TimeoutError:
                if attempt == max_retries - 1:
                    raise OptimizationError(f"LLM调用超时 ({timeout}s)") from None
                wait_time = retry_delay * (2**attempt)
                logger.warning(f"LLM timeout (attempt {attempt + 1}/{max_retries}), retry in {wait_time}s")
                await asyncio.sleep(wait_time)

            except Exception as e:
                if attempt == max_retries - 1:
                    raise OptimizationError(f"LLM调用失败: {e!s}") from e
                wait_time = retry_delay * (2**attempt)
                logger.warning(f"LLM error (attempt {attempt + 1}/{max_retries}): {e}, retry in {wait_time}s")
                await asyncio.sleep(wait_time)

        raise OptimizationError("LLM optimization failed after all retries")

    def _build_optimization_prompt(
        self, skill: SkillMetadata, quality_score: SkillQualityScore, content: str | None = None
    ) -> str:
        """构建优化prompt

        基于skill当前质量评分，生成针对性的优化提示。
        """
        # 1. 指令与任务要求 (Stable Prefix)
        prompt = f"""You are an expert in optimizing AI agent skills.

Goal: Improve success rate, reduce tokens, and optimize execution time.
Instructions:
- Analyze the current skill implementation below.
- Refactor the prompt or logic to be more robust and efficient.
- Ensure the output is valid SKILL.md markdown with YAML frontmatter.
- Focus on:
  1. Improving success rate (reliability)
  2. Reducing token usage (efficiency)
  3. Optimizing execution time
  4. Enhancing user experience

Current Skill Implementation:
```markdown
{content or "[Content not available - optimize based on description]"}
```

Please output the complete optimized SKILL.md content.

<telemetry>
Skill Name: {skill.name}
Description: {skill.description}
Current Performance Metrics:
- Success Rate: {quality_score.success_rate:.2%}
- Token Efficiency: {quality_score.token_efficiency:.2%}
- Execution Time: {quality_score.execution_time:.2%}
- User Satisfaction: {quality_score.user_satisfaction:.2%}
- Overall Score: {quality_score.overall_score:.2%}
</telemetry>
"""
        return prompt
