# conflict_gate/

## 架构概述

多 Bot 并行产出冲突对账与合并前拦截门（Parallel Work Conflict Reconciliation Gate）：
当多个 Agent Profile 或并发子代理各自报告「已完成」但尝试写回修改同一工作区文件、工件、配置项或看板卡片时，在合并/汇总前自动检测写集碰撞（write-set collision）：
1. **写集指纹聚合**：基于 `(resource_id, mutation_type, content_hash)` 识别多并发 Worker 的双写与多写；
2. **冲突硬拦截门禁（Fail-Closed）**：若不同 Worker 产出不同 Hash，标记为 `conflict_pending` 并阻断静默覆盖（is_blocked=True）；相同 Hash 则判定为幂等安全写；
3. **四策略对账解决**：提供 `keep_worker_a`、`keep_worker_b`、`three_way_merge` 与 `abort_both` 显式对账机制。

## 文件清单

| 文件 | 地位 | 职责 | I/O/P |
|------|------|------|-------|
| `__init__.py` | 门面 | 统一导出冲突门禁检测器与类型契约 | ✅ |
| `types.py` | 核心 | 写集指纹、冲突条目、状态枚举与门禁裁决结果契约 | ✅ |
| `detector.py` | 核心 | 线程安全写集冲突检测与四策略对账解决器 | ✅ |
