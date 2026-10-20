# durable_dispatch/

## Overview
Hermes Fabric 确定性远程分发与持久化对等日志内核（Fabric Deterministic Remote Dispatch & Durable Journals）：
在分布式、跨进程、沙箱多 Agent 调度中，提供确定性远程分发通道、协调器与对等 Worker 双向持久化日志（Durable Journals）、崩溃后幂等状态自愈恢复（Idempotent Recovery）、协调器主体鉴权（Coordinator-Principal Auth）、执行前工作契约策略重核验（Pre-start Policy Revalidation）与有界证据准入门禁（Bounded Evidence Admission）。

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Facade | 门面导出 `DurableRemoteDispatchEngine`、`DurableDispatchJournal`、`WorkContract`、`EvidenceItem`、`RecoveryPlan` 等 | — |
| `types.py` | Core | 核心数据模型：日志条目类型枚举 `JournalEntryType`、持久化日志记录 `DispatchJournalEntry`、工作契约 `WorkContract`、有界证据 `EvidenceItem`、分发收据 `DispatchReceipt` 与自愈恢复计划 `RecoveryPlan` | ✅ |
| `journal.py` | Core | 单调递增序列持久化日志账本：管理分发事务日志的顺序追加、SHA-256 完整性摘要与历史全景回溯 | ✅ |
| `engine.py` | Core | 确定性分发与自愈恢复引擎：提供契约签发、Fail-Closed 执行前策略重校验、64KB/1MB 有界证据准入门禁与崩溃后幂等自愈规划 | ✅ |
