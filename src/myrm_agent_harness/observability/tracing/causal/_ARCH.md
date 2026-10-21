# observability/tracing/causal/

## 架构概述

单次任务因果链路追踪（Causal Trace Span Tree）与零依赖优雅降级 OpenTelemetry 遥测接入层。上级文档：[../_ARCH.md](../_ARCH.md)。

## 文件清单

| 文件 | 地位 | 职责 | I/O/P |
|------|------|------|-------|
| `__init__.py` | 入口 | 导出 CausalTracer, TraceSpan, SpanKind, SpanStatus, ZeroDepOTelBridge | ✅ |
| `spans.py` | 模型 | 因果 TraceSpan 树节点模型、阶段类型枚举与耗时度量 | ✅ |
| `tracer.py` | 引擎 | 单次请求 Span 上下文栈管理、自动建立父子因果关联与高敏数据脱敏 | ✅ |
| `otel_bridge.py` | 适配器 | 零外部依赖的优雅降级 OTel 遥测桥，支持本地轻量 JSON 导出 | ✅ |
