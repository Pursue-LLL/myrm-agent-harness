# Durable Revision Architecture & Specification

## 1. 模块定位
`durable_revision` 是 Myrm Agent Harness 的核心记忆并发写持久化与修订安全（Concurrent Writes Durable & Revision Safety）底层执行引擎。
遵循框架设计原则，定位为纯单机、无多租户、工业级可靠性的本地持久化与并发控制基础设施。

## 2. 核心职责
1. **细粒度写锁与全抖动退避（KeyLockManager）**：
   - 基于页面/文档键维度的细粒度锁隔离，彻底消除粗粒度库级锁引发的假性争用；
   - 采用 Full Jitter Exponential Backoff 算法防范多智能体惊群与活锁，重试超限安全收敛为 `RETRYABLE_CONTENTION` 收据。
2. **单调权威修订与 MVCC 快照读（MVCCRevisionEngine）**：
   - 维护原子单调递增权威版本号（Canonical Revision）；
   - 提供多版本快照读（SnapshotReadView），支持原子获取特定版本的内容、标签及撤回/墓碑态，读写互不阻塞；
   - 支持不可变安全回滚与墓碑标记。
3. **两阶段意图预写与崩溃恢复（TwoPhaseIntentWAL）**：
   - Phase 1 预写意图日志并计算 CRC32 校验码；
   - 故障重启或异常中断时扫描 WAL，未决完整意图自愈重放，残损截断意图隔离并标记 `FAILED_DURABLE`。
4. **7 态类型化变更收据（ChangeReceipt）**：
   - 严格枚举：`APPLIED`, `RETRYABLE_CONTENTION`, `VALIDATION_FAILED`, `QUARANTINED`, `SUPERSEDED`, `REVERTED`, `FAILED_DURABLE`，附带错误上下文。
5. **统一门面协调器（DurableRevisionSuite）**：
   - 对外提供标准化的 `write()`, `read_snapshot()`, `rollback()`, `get_receipt()`, `get_stats()` 统一接口。
