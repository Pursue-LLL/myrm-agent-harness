# otel_degrade/

## Overview
OpenTelemetry 缺失时优雅降级与可观测探针零硬依赖（Graceful Degrade Without OpenTelemetry）核心子包。
确立“可观测代码绝不能成为系统故障源”的硬性工程纪律：在环境未安装 `opentelemetry` 依赖、或环境变量显式禁用时，探针静默降级为零开销 No-Op 空操作（`NoOpTracer`、`NoOpSpan`、`NoOpMeter`），业务执行循环 100% 保持顺畅无阻断。

## Architecture & Responsibilities

- `models.py`:
  - `OtelPostureState`: 运行姿态枚举 (`ACTIVE`, `DEGRADED_NO_OP`, `DISABLED`)；
  - `OtelDegradeStatus`: 降级诊断状态与拦截统计实体。
- `runtime.py`:
  - `NoOpSpan`: 契约兼容的标准 TraceSpan 降级实现，保留上下文管理器与异常原样透传行为；
  - `NoOpTracer`: 零硬依赖的 Tracer 降级实现；
  - `NoOpMeter` & `NoOpCounter`: 指标上报降级实现；
  - `GracefulOtelRuntime`: 动态检测环境依赖、安全获取 Tracer/Meter、输出运行态自检诊断。
- `__init__.py`: 统一门面导出。

## File Index

| File | Role | Description | I/O/P |
|---|---|---|---|
| `models.py` | 数据模型 | OtelPostureState 枚举与 OtelDegradeStatus 状态契约 | ✅ |
| `runtime.py` | 核心引擎 | NoOpSpan/NoOpTracer/NoOpMeter 降级元语与 GracefulOtelRuntime 运行时 | ✅ |
| `__init__.py` | 模块入口 | 聚合导出核心模型与降级运行时接口 | ✅ |
