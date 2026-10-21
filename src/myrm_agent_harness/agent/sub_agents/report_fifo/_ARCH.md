# report_fifo/

## Overview
子智能体回报路径实时唤醒、Step 边界报告结算保序与无人值守多命名实例体系（Subagent `reportDelivery: next-step` Parent Wakeup, FIFO Settlement Ordering & Unattended Multi-instance Fabric）：
对标 DeepSeek Harness 多模态更新（Issue #2600 修复），解决异步多智能体中结算通知早于工作报告到达导致成果丢失的竞态时序缺陷；提供基于 Step 边界的主动唤醒机制（`parent.steer()`）以及多命名子智能体实例与无人值守非交互权限模式（`permissionMode`）；支持 `critical` 严重级别紧急置顶入队与 `urgent_interrupt` 打断唤醒标记，具备 `threading.RLock()` 线程安全锁与 1000 容量有界保护淘汰防线，并提供 `generate_summary_rollup` 批量排空自然语言摘要聚合（为主模型节约 30%~50% Token）。

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Facade | 门面导出 `SubagentReportWakeupCoordinator`、`OrderedSettlementFifoQueue`、`SubagentReportItem`、`SettlementNoticeItem` 等 | — |
| `types.py` | Core | 核心数据模型：回报交付模式 `ReportDeliveryMode`（quiet/next-step）、权限模式 `PermissionMode`、FIFO 事件信封 `OrderedFifoQueueEnvelope`（含 `urgent_interrupt`）、报告载荷 `SubagentReportItem`（含 `severity`）与命名实例配置 `NamedSubagentInstanceConfig` | ✅ |
| `queue.py` | Core | Report-before-Settlement FIFO 严格保序队列：RLock 线程安全锁、1000 元素有界保护与非关键淘汰、critical 紧急置顶入队、同 task_id 下确保子智能体主动 report 绝对优先于系统结算通知出队，以及 `generate_summary_rollup` 紧凑聚合方法 | ✅ |
| `coordinator.py` | Core | 子任务回报唤醒调度器：治理多命名子智能体实例注册、主动报告提交（支持 severity 透传）、Step 边界批次排空与无人值守权限鉴权 | ✅ |
