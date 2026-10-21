"""进程级文件描述符软限制（RLIMIT_NOFILE）自适应抬升模块.

对标外部工业级基线（如 openai-codex 8519cde1ba）：
在受管守护进程启动时将软限制抬到 4096 并以继承的硬限制封顶，解决 macOS 图形会话/桌面 sidecar 默认 256
导致 120+ 会话即触发 Too many open files 崩溃的物理缺陷。

[INPUT]
- __future__
- logging

[OUTPUT]
- logger
- get_nofile_limits
- raise_nofile_soft_limit

[POS]
进程级文件描述符软限制（RLIMIT_NOFILE）自适应抬升模块.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# 尝试导入 Unix resource 模块
try:
    import resource
except ImportError:
    resource = None  # type: ignore[assignment]


def get_nofile_limits() -> tuple[int, int]:
    """获取当前进程的 (软限制, 硬限制).

    若当前运行平台不支持 resource 模块（如 Windows），返回 (-1, -1).
    """
    if resource is None or not hasattr(resource, "RLIMIT_NOFILE"):
        return (-1, -1)
    try:
        soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        return (int(soft), int(hard))
    except (OSError, ValueError) as exc:
        logger.warning("Failed to getrlimit RLIMIT_NOFILE: %s", exc)
        return (-1, -1)


def raise_nofile_soft_limit(target: int = 4096) -> tuple[int, int]:
    """在进程启动阶段安全抬高自身 RLIMIT_NOFILE 软限制.

    算法规则：
    1. 目标值取 max(当前软限制, min(硬限制, target))；
    2. 已有更高软限制则保持，绝不压低；
    3. 若 setrlimit 抛错（例如无特权），记录 WARNING 日志并优雅降级，绝不中断进程；
    4. 返回最终生效的 (软限制, 硬限制).
    """
    if resource is None or not hasattr(resource, "RLIMIT_NOFILE"):
        logger.debug("Platform does not support resource.RLIMIT_NOFILE, skipping limit lift")
        return (-1, -1)

    try:
        cur_soft, cur_hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    except (OSError, ValueError) as exc:
        logger.warning("Cannot read current RLIMIT_NOFILE limits: %s", exc)
        return (-1, -1)

    # 如果硬限制为负数（部分平台表示 unlimited），按 target 处理
    effective_hard = cur_hard if cur_hard > 0 else target

    # 计算目标软上限：不低于当前软上限，且不超过硬上限
    target_soft = max(cur_soft, min(effective_hard, target))

    if target_soft <= cur_soft:
        logger.debug(
            "Current soft limit %d already meets or exceeds target %d (hard: %d)",
            cur_soft,
            target_soft,
            cur_hard,
        )
        return (cur_soft, cur_hard)

    try:
        resource.setrlimit(resource.RLIMIT_NOFILE, (target_soft, cur_hard))
        logger.info(
            "Successfully raised RLIMIT_NOFILE soft limit from %d to %d (hard: %d)",
            cur_soft,
            target_soft,
            cur_hard,
        )
        return (target_soft, cur_hard)
    except (OSError, ValueError, PermissionError) as exc:
        logger.warning(
            "Failed to raise RLIMIT_NOFILE soft limit to %d: %s. Keeping original limit %d",
            target_soft,
            exc,
            cur_soft,
        )
        return (cur_soft, cur_hard)
