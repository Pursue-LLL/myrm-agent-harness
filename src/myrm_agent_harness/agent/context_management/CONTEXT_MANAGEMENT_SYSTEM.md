# Context Management System Design

> Agent 上下文工程子系统。在 LangGraph 消息流上实现过滤、压缩、摘要、缓存标记与预算锁定，保护 Prompt Prefix Cache 并控制 token 成本。

---

## 设计目标

1. **Prefix Cache 友好**：稳定前缀（system/tools）与可变后缀（history）分离；压缩/摘要不破坏 cache 指纹
2. **三层降载**：Filter → Compress → Summarize，逐级降级
3. **会话级串行**：同一 chat 的上下文变更通过 session lock 串行化，避免竞态
4. **可观测**：tracking 模块记录 artifact、archive refetch 成本与 restore-block 事件

---

## 系统架构

```
┌──────────────────────────────────────────────────────────────┐
│ context_pipeline_middleware (middlewares/)                    │
│   create_context_pipeline_middleware()                        │
└────────────────────────────┬─────────────────────────────────┘
                             ▼
┌──────────────────────────────────────────────────────────────┐
│ pipeline/engine.py — SessionLock + 顺序处理器链               │
└────────────────────────────┬─────────────────────────────────┘
                             ▼
    ┌────────────┬───────────┴───────────┬────────────┐
    ▼            ▼                       ▼            ▼
 processors/  strategies/          archive_      tracking/
 (过滤/裁剪/   (Filter/Compress/    checkpoint/   (指标/artifact
  摘要/缓存)    Summarize)           (Lite-LLM)    追踪)
    │            │                       │            │
    └────────────┴───────────┬───────────┴────────────┘
                             ▼
                    infra/ — schemas, budget, token estimate
                             │
                    preheat.py — Anthropic/Qwen prefix 预热
                    pre_compact_service.py — 压缩前语义召回
```

---

## 核心组件

| 模块 | 职责 |
|------|------|
| `context.py` | Agent 运行时 ContextVar 容器（user/session/workspace） |
| `pipeline/engine.py` | 处理器链引擎 + session lock |
| `pipeline/processors/` | 过滤、cache-TTL 裁剪、pre-compaction recall、摘要、规范化、cache-control 标记 |
| `strategies/` | Filter / Compress / Summarize 三档策略；Summarize 用 structured output 防 JSON 脆弱性 |
| `infra/` | Token 估算、预算管理、schemas、cache policy |
| `archive_checkpoint/` | Lite-LLM archive summary 检查点 Protocol + 持久化 |
| `tracking/` | Artifact 追踪、task metrics、archive 读预算 |
| `preheat.py` | 显式 cache provider 前缀预热（Agent 启动 + 压缩后） |
| `pre_compact_service.py` | 压缩前 MemoryPreCompact 回调 |

---

## 与 middlewares 协作

- **入口**：`middlewares/context_pipeline_middleware.py` 在 Agent 图构建时注入
- **辅助**：`context_pipeline_helpers.py` 解析压缩意图、tool schema fingerprint
- **记忆注入**：`memory_context_middleware.py` 注入 `<user_memory_context>`（与 pipeline 互补，非重复）

---

## 与 toolkits/memory 边界

| 层 | 职责 |
|----|------|
| `toolkits/memory/` | MemoryManager、向量/关系存储、召回 Protocol |
| `context_management/` | **消息流**上的预算、压缩、摘要、cache 标记 |
| `context_bundle/` (toolkits) | 磁盘卷布局 SSOT |

context_management **不实现**向量检索；通过 IntegrationProvider / pre_compact 回调与 memory 协作。

---

## 理论参考

- [CONTEXT_ENGINEERING.md](CONTEXT_ENGINEERING.md) — 行业上下文工程理论
- [PROMPT_CACHE_PRACTICE.md](PROMPT_CACHE_PRACTICE.md) — 框架 cache 实践

---

## 扩展指南

新增 processor：

1. 继承 `pipeline/base.py::BaseProcessor`
2. 注册到 `pipeline/processors/` 并在 engine 顺序中声明位置
3. 更新 `pipeline/processors/_ARCH.md` 与本文档
4. 单测放 `tests/agent/context_management/` 或 `tests/toolkits/` 对应目录

---

## 参考资料

- [context_management/_ARCH.md](_ARCH.md)
- [middlewares/MIDDLEWARE_SYSTEM.md](../middlewares/MIDDLEWARE_SYSTEM.md)
