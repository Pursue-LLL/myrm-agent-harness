# Event Log System Design

> 全量事件历史子系统。在 LangGraph Checkpointer 之外提供完整 Agent 运行轨迹，支撑 Trace 分析、技能进化证据挖掘、数据集导出与 CLI 摘要。

---

## 设计目标

1. **Checkpointer 互补**：Checkpointer 保存图状态；EventLog 保存细粒度事件流（tool/llm/token）
2. **可选注入**：通过 `event_log_backend` 注入 BaseAgent，未配置时零开销
3. **读侧分析**：analytics / evidence_extractor 供技能进化 idle 任务消费
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
      ├─ trace_builder.py — llm_request + token_usage → LLMCallRecord；tool_start/tool_end 按 tool_call_id 配对，`tasks_steps` 流式步骤读侧兼容 → 指令血缘（配对/LLM/tasks_steps 逻辑分别由 _pairing.py/_llm.py/_tasks_steps.py 承载，共享工具函数与 `_EVENT_META_KEYS` 元数据键集合在 _common.py）
      ├─ analytics.py / analytics_queries.py — 读侧聚合
      ├─ evidence_extractor.py — Trace 证据挖掘（idle → skill evolution）
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
| `trace_builder.py` | LLM 调用时间线重建 + tool_call_id 血缘配对（配对/LLM/tasks_steps 逻辑由 `_pairing.py`/`_llm.py`/`_tasks_steps.py` 承载，共享工具函数与 `_EVENT_META_KEYS` 元数据键集合在 `_common.py`） |
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

## 扩展 Entry 隔离机制（Custom vs CustomMessage）

系统严格区分两类插件扩展事件，实现存储与模型上下文的物理隔离：

1. **`custom`（私有簿记事件）**：
   - 载荷类型：`CustomStatePayload`
   - 行为：写入事件日志文件（FileEventLogBackend）并由 `trace_builder` 归纳为 `ExecutionTrace.custom_states`，供前端/桌面端「插件状态检查器」审计；
   - 约束：不进入 LLM 上下文模型消息流，0 Token 泄漏，杜绝模型幻觉。

2. **`custom_message`（模型可见通知）**：
   - 载荷类型：`CustomMessagePayload`
   - 行为：进入对话上下文，在服务端被包装为携带插件元数据的 `HumanMessage`，并在前端渲染为专有的 `CustomMessageCard`；同时由 `trace_builder` 归集为 `ExecutionTrace.custom_messages`，供回放审计与端到端上下文重构；
   - 保留策略：支持 `retention: "ephemeral"`（Compaction 摘要时自动剔除临时告警）与 `retention: "persistent"`（长期保留）。

---

## 扩展指南

1. 实现 `EventLogBackend` Protocol → 注册到 Agent 构造参数
2. 新事件类型 → 更新 `types.py` + logger 发射点 + trace_builder
3. 更新 [event_log/_ARCH.md](_ARCH.md)

---

## 参考资料

- [event_log/_ARCH.md](_ARCH.md)
