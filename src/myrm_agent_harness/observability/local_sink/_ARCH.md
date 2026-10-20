# Local Disk Telemetry Sink Architecture

## Overview
本子包实现 OpenTelemetry 缺失时的 Opt-In 本地盘可观测性落盘兜底引擎（`LoopForgeOtelOptionalDashboard`），专为离线桌面端（Desktop）、本地开发者单机环境（Local）以及隔离无网络沙箱设计。

## Core Invariants
1. **零硬依赖与安全隔离**：
   - 当环境中未安装 `opentelemetry` 或无法连接远端 OTLP Collector 时，系统业务执行 100% 顺畅，绝不抛出任何追踪相关异常。
2. **Opt-In 本地盘落盘兜底 (Local Disk Fallback Sink)**：
   - 支持通过配置或环境变量 `MYRM_LOCAL_TELEMETRY_DISK=1` 开启本地追加写落盘（JSONL 格式）；
   - 内部集成定长环形内存缓冲区（RingBuffer 500 条），支持极速零延迟前端调用链回放。
3. **安全容错与零主业务侵入**：
   - 所有的磁盘 I/O 操作均受线程锁与安全异常守卫保护，哪怕磁盘已满或写入权限异常，也绝不影响核心 Agent 运行。

## File Layout
| 文件 | 类型 | 职责 | 状态 |
| :--- | :--- | :--- | :--- |
| `models.py` | 核心实现 | `LocalSpanRecord`, `LocalMetricRecord`, `LocalSinkStatus`, `LocalDiskTelemetrySink` 落盘引擎 | ✅ |
| `__init__.py` | 门面导出 | 聚合导出模块内所有模型与本地盘引擎类 | ✅ |
| `_ARCH.md` | 架构文档 | 模块定位、核心不变量与文件表 | ✅ |
