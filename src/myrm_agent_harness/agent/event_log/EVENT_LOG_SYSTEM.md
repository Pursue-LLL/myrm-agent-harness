# Event Log System Design

> 全量事件历史子系统。在 LangGraph Checkpointer 之外提供完整 Agent 运行轨迹，支撑 Trace 分析、Task-Adaptive Context、数据集导出与 CLI 摘要。

---

## 设计目标

1. **Checkpointer 互补**：Checkpointer 保存图状态；EventLog 保存细粒度事件流（tool/llm/token）
2. **可选注入**：通过 `event_log_backend` 注入 BaseAgent，未配置时零开销
3. **读侧分析**：analytics / evidence_extractor 供 Task-Adaptive 与 idle 任务消费
4. **导出管道**：dataset_export 支持 ShareGPT/Alpaca/OpenAI JSONL + PII 脱敏

---

## 系统架构

```
BaseAgent.run()
      │ event_log_backend (Protocol)
      ▼
┌─────────────┐     ┌──────────────────┐
│ EventLogger │────▶│ backends/        │
│ (logger.py) │     │ FileEventLogBackend │
└─────────────┘     └──────────────────┘
      │
      ├─ trace_builder.py — llm_request + token_usage → LLMCallRecord
      ├─ analytics.py / analytics_queries.py — 读侧聚合
      ├─ evidence_extractor.py — Task-Adaptive 证据挖掘（idle）
      ├─ llm_observability.py — prompt preview 截断记录
      └─ dataset_export/ — 质量过滤 + 格式转换 + exporter
```

---

## 核心组件

| 模块 | 职责 |
|------|------|
| `protocols.py` | `EventLogBackend` Protocol — 框架扩展点 |
| `logger.py` | 集成 façade，注入 BaseAgent |
| `types.py` / `trace_types.py` | 事件 DTO SSOT |
| `trace_builder.py` | LLM 调用时间线重建 |
| `backends/` | 内置存储实现（文件/内存） |
| `dataset_export/` | 训练数据导出管道 |
| `cli_summary.py` | CLI 摘要生成 |

---

## 与 observability 边界

| | event_log | observability |
|--|-----------|---------------|
| 数据 | 持久事件历史 | Prometheus / Doctor / log trace_id |
| 用途 | 回放、导出、Trace 分析 | 运行时监控桥接 |

---

## 扩展指南

1. 实现 `EventLogBackend` Protocol → 注册到 Agent 构造参数
2. 新事件类型 → 更新 `types.py` + logger 发射点 + trace_builder
3. 更新 [event_log/_ARCH.md](_ARCH.md)

---

## 参考资料

- [event_log/_ARCH.md](_ARCH.md)
- [middlewares/MIDDLEWARE_SYSTEM.md](../middlewares/MIDDLEWARE_SYSTEM.md) — task_adaptive_middleware 消费 Trace
