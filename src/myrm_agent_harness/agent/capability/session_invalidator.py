"""会话回合边界能力纪元校验器与 JIT 增量提示词重建模块。

通过在回合边界执行 O(1) 毫秒级 Epoch 比对与双重检查锁定 (Double-Checked Locking)，
实现智能体配置变更在当前会话中无缝热生效，杜绝多协程并发状态撕裂与无谓冷启动。

[INPUT]
- __future__
- asyncio
- dataclasses
- logging
- time
- typing

[OUTPUT]
- logger
- CompiledAgentContext
- SessionCapabilityState
- ValidationResult
- TurnBoundaryEpochValidator

[POS]
会话回合边界能力纪元校验器与 JIT 增量提示词重建模块。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import logging
import time
from typing import Callable, Coroutine, Dict, Optional, Tuple

from myrm_agent_harness.agent.capability.epoch_hasher import (
    CanonicalCapabilityManifest,
    CapabilityEpochHasher,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class CompiledAgentContext:
    """当前回合生效的不可变智能体运行时上下文快照。"""

    capability_epoch: str
    system_prompt: str
    available_tools: Tuple[str, ...]
    available_skills: Tuple[str, ...]
    model_id: str
    reasoning_effort: Optional[str] = None
    temperature: float = 0.7
    created_at_mono: float = field(default_factory=time.monotonic)


@dataclass(slots=True)
class SessionCapabilityState:
    """会话持有的能力纪元与生效上下文状态容器。"""

    session_id: str
    agent_id: str
    cached_epoch: Optional[str] = None
    active_context: Optional[CompiledAgentContext] = None
    _rebuild_lock: asyncio.Lock = field(default_factory=asyncio.Lock)


@dataclass(frozen=True)
class ValidationResult:
    """回合边界能力纪元校验结果。"""

    is_rebuilt: bool
    current_epoch: str
    context: CompiledAgentContext
    reason: str


class TurnBoundaryEpochValidator:
    """回合边界能力纪元校验与 JIT 增量重构器。"""

    @staticmethod
    def build_context_from_manifest(
        manifest: CanonicalCapabilityManifest,
        epoch: str,
    ) -> CompiledAgentContext:
        """从权威能力清单同步编译出运行时不可变上下文快照。"""
        # 组装纯净 System Prompt
        prompt_parts: list[str] = []
        if manifest.soul_content:
            prompt_parts.append(manifest.soul_content.strip())
        if manifest.system_prompt:
            prompt_parts.append(manifest.system_prompt.strip())

        full_prompt = "\n\n".join(prompt_parts)

        return CompiledAgentContext(
            capability_epoch=epoch,
            system_prompt=full_prompt,
            available_tools=tuple(sorted(manifest.tools)),
            available_skills=tuple(sorted(manifest.skills)),
            model_id=manifest.model_id,
            reasoning_effort=manifest.reasoning_effort,
            temperature=manifest.temperature,
        )

    @classmethod
    async def validate_and_rebuild_if_stale(
        cls,
        session_state: SessionCapabilityState,
        latest_manifest: CanonicalCapabilityManifest,
    ) -> ValidationResult:
        """在用户发起新回合前执行 O(1) 比对，必要时原子 JIT 增量重建。

        使用双重检查锁定 (Double-Checked Locking)，杜绝并发请求双重重构。
        """
        target_epoch = CapabilityEpochHasher.calculate_epoch(latest_manifest)

        # 1. 快速检查 (Fast-Path)：稳态下 O(1) 字符串比对（< 0.5 微秒）
        if (
            session_state.cached_epoch == target_epoch
            and session_state.active_context is not None
        ):
            return ValidationResult(
                is_rebuilt=False,
                current_epoch=target_epoch,
                context=session_state.active_context,
                reason="Capability epoch matched; reused pre-compiled context",
            )

        # 2. 慢速路径 (Slow-Path)：双重检查锁定防并发竞态
        async with session_state._rebuild_lock:
            # 再次检查，防止多协程排队唤醒后重复构建
            if (
                session_state.cached_epoch == target_epoch
                and session_state.active_context is not None
            ):
                return ValidationResult(
                    is_rebuilt=False,
                    current_epoch=target_epoch,
                    context=session_state.active_context,
                    reason="Rebuild completed by concurrent request; reused context",
                )

            logger.info(
                "Epoch mismatch for session %s (old=%s, new=%s); executing JIT rebuild",
                session_state.session_id,
                session_state.cached_epoch,
                target_epoch,
            )

            # 原子 JIT 编译新上下文快照
            new_context = cls.build_context_from_manifest(
                manifest=latest_manifest,
                epoch=target_epoch,
            )

            # 原子替换会话状态
            session_state.active_context = new_context
            session_state.cached_epoch = target_epoch

            return ValidationResult(
                is_rebuilt=True,
                current_epoch=target_epoch,
                context=new_context,
                reason="Capability epoch updated; JIT context rebuild succeeded",
            )
