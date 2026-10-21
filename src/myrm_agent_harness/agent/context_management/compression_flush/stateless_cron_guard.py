"""定时自动化任务无状态记忆隔离与自包含防护网关。

针对 Cron 定时任务与系统级派生自动化，强制跳过全量 User Profile 易变层注入，
剥离主会话上下文污染切片，确保提示词自包含与严格无状态执行。

[INPUT]
- agent.context_management.compression_flush.types::StatelessCronSpec (POS:
  多智能体与长会话上下文压缩即时持久化刷盘协议核心类型。)

[OUTPUT]
- StatelessCronContextGuard: 自动化 Cron 定时任务无状态记忆隔离防护器。

[POS]
定时自动化任务无状态记忆隔离与自包含防护网关。
"""

from __future__ import annotations

import re

from myrm_agent_harness.agent.context_management.compression_flush.types import (
    StatelessCronSpec,
)


class StatelessCronContextGuard:
    """自动化 Cron 定时任务无状态记忆隔离防护器。"""

    # 匹配主会话注入的各类用户画像与即时认知心智切片
    _USER_PROFILE_PATTERNS: tuple[re.Pattern[str], ...] = (
        re.compile(r"<!--\s*\[USER\s+DIALECTIC\s+MIND\].*?-->.*?(?=\n\n|\Z)", re.DOTALL | re.IGNORECASE),
        re.compile(r"<!--\s*\[USER\s+PROFILE\].*?-->.*?(?=\n\n|\Z)", re.DOTALL | re.IGNORECASE),
        re.compile(r"#\s*USER\s+PROFILE\s*&.*?(?=\n\n|\Z)", re.DOTALL | re.IGNORECASE),
    )

    @classmethod
    def sanitize_cron_prompt(
        cls, raw_prompt: str, spec: StatelessCronSpec
    ) -> tuple[str, bool]:
        """清洗 Cron 任务提示词，根据规格剥离主会话用户画像与易变关切。

        Returns:
            (sanitized_prompt, was_modified)
        """
        if not spec.strip_user_profile:
            return raw_prompt, False

        cleaned = raw_prompt
        was_modified = False

        for pattern in cls._USER_PROFILE_PATTERNS:
            new_cleaned = pattern.sub("", cleaned).strip()
            if new_cleaned != cleaned:
                cleaned = new_cleaned
                was_modified = True

        return cleaned, was_modified

    @classmethod
    def validate_self_contained(
        cls, prompt: str, min_chars: int = 10
    ) -> bool:
        """校验 Cron 提示词是否具备自包含性 (非空且具备基础语义长度)。"""
        trimmed = prompt.strip()
        return len(trimmed) >= min_chars
