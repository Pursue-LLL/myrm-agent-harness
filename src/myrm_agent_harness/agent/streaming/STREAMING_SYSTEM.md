# Streaming System Design

> BaseAgent 事件处理管道。将 LangGraph `astream` 原始 chunk 转换为前端/通道可消费的 SSE 业务事件，并承载流式恢复、模型升级与 artifact 转发。

---

## 设计目标

1. **统一事件契约**：`streaming/types.py` 定义 AgentEventType 与 payload DTO
2. **流式清洗**：reasoning/escalation 标记跨 chunk 缓冲，不泄漏到用户可见输出
3. **多层恢复**：overflow、failover、escalation、truncation、steering、subagent、goal continuation
4. **Artifact 转发**：file/UI/inline artifact 与 multimodal tool output（TOOL_IMAGE_OUTPUT）

---

## 系统架构

```
BaseAgent.run() / astream()
        │
        ▼
┌───────────────────┐
│ stream_executor.py │  StreamExecutor — 生命周期编排
│  (mixins)         │
└─────────┬─────────┘
          │
    ┌─────┴─────┬─────────────┬──────────────┐
    ▼           ▼             ▼              ▼
stream_     event_        artifact_      stream_
dispatcher  handlers      events         recovery*
    │           │             │              │
    ▼           ▼             ▼              ▼
 output_queue  SSE DTO    registry/UI    failover/escalation/
 (asyncio)     转换        事件            truncation/oneshot/
                                                    continuation
```

### Mixin 拆分（stream_executor 组合）

| Mixin / 模块 | 职责 |
|--------------|------|
| `stream_dispatcher.py` | chunk → output_queue；swarm_fission GraphInterrupt 专路由 |
| `recovery/stream_recovery.py` | 主恢复策略组合（overflow/failover/escalation/retry/iteration-limit） |
| `recovery/stream_recovery_truncation.py` | max-token 续写、truncated tool-call 重试 |
| `recovery/stream_recovery_oneshot.py` | THINKING_SIGNATURE / DUPLICATE_TOOL_USE_ID / IMAGE_TOO_LARGE / MEDIA_REJECTED / ALLOWED_TOOLS_TOOL_CHOICE_REJECTED / LONG_CONTEXT_TIER 等一次性恢复（支持单图超限收缩与多图累积超限历史轮次聚合降级保底，WebUI progress step: `thinking_signature_recovery`, `tool_history_recovery`, `image_shrink_recovery`, `long_context_tier_recovery`, `vision_fallback_recovery`, `media_rejected_recovery`, `allowed_tools_rejected_recovery`） |
| `recovery/stream_recovery_continuation.py` | steering、subagent 完成、goal continuation |
| `stream_compactor.py` | 高频流式文本片段合并缓冲（容量/时间/事件类型变更/显式 flush，后台看门狗防幽灵延迟） |
| `stream_buffer.py` | SSE 断线重连回复缓冲：内存滑动窗口 + GlobalStreamRegistry（Last-Event-ID 短断连复连，无磁盘持久化） |

---

## 清洗与纪律

| 模块 | 职责 |
|------|------|
| `reasoning_scrubber.py` | 非标准模型 thinking 标签 → 独立 THINKING 事件 |
| `escalation_scrubber.py` | `<<<NEEDS_PRO>>>` 检测 → 模型升级信号 |
| `repetition_scrubber.py` | Token/N-Gram 滑窗死循环监测与 Markdown 代码块语法感知自适应熔断 |
| `model_discipline.py` | 按模型族注入执行纪律 prompt |
| `channel_output_hints.py` | 按通道（Telegram/WhatsApp/voice）输出格式提示 |

---

## 消息与步骤构建

| 模块 | 职责 |
|------|------|
| `message_builder.py` | 消息准备与时间戳注入 |
| `step_builder.py` | 前端步骤 UI 数据（tool name + args） |
| `utils.py` | 上下文校验、行为规则、tool name 规范化 |
| `source_tracker.py` | 来源引用转发 |

---

## 与 observability 边界

- **streaming/** — Agent 运行时事件转换与恢复（热路径）
- **streaming/broadcast/** — ToolCallBroadcaster→EventLogger→SSE（UI）；ToolBroadcastBus 供 server 侧订阅

streaming 产出的事件可被 observability 层订阅，但不反向依赖。

---

## 扩展指南

1. 新 SSE 事件类型 → `types.py` 枚举 + `event_handlers.py` 转换 + 前端契约
2. 新恢复策略 → 独立 mixin 模块，由 `recovery/stream_recovery.py` 组合
3. 禁止在 streaming 层写业务 channel 逻辑 → `myrm-agent-server/app/core/channel_bridge/` 或 Server

---

## 参考资料

- [streaming/_ARCH.md](_ARCH.md) — 完整文件清单
- [base_agent.py](../base_agent.py) — run/astream 入口
- [middlewares/MIDDLEWARE_SYSTEM.md](../middlewares/MIDDLEWARE_SYSTEM.md)
