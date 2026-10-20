# observability/cron_doctor/

## Overview
Cron 自动化任务舰队全景健康体检医生与预防性隐患自查引擎（Cron Fleet Doctor & Preventive Health Inspector）。
借鉴 Hermes Agent 核心架构 `hermes cron doctor` 生产级实践，对全量处于活跃状态的定时任务执行只读扫描，严格判定 6 大健康门禁（执行失败、交付失败、交付未验真、调度时间逾期滞后、脚本文件缺失或 AST 异常、沙箱专属工作目录缺失），并提供结构化体检诊断报告与精准外科手术式修复建议（Quick Fix）。

## File & Module Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package Facade | 导出 Cron 舰队体检医生核心模型与检查引擎。 | ✅ |
| `models.py` | Data Contracts | 定义 `CronHealthIssueCategory`、`CronJobHealthCheckTarget`、`CronJobHealthIssue` 与 `CronFleetDoctorReport` 强类型契约。 | ✅ |
| `doctor.py` | Core Engine | 实现 `CronFleetDoctor`，执行六大核心只读门禁检查并编译多任务体检诊断报告。 | ✅ |

## Architectural Constraints
1. **只读安全性**：体检过程绝对只读，严禁在扫描阶段产生写操作或阻断现有调度运行。
2. **零 Any 类型**：严格采用 Python 强类型与不可变 dataclass 契约。
3. **精准溯源**：每一条发现的健康隐患必须包含精准的分类 `category`、严重级别 `severity` 与直观修复建议 `suggested_fix`。
