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
| `stream_dispatcher.py` | chunk → output_queue；`__interrupt__` 分片交 `interrupt_events.py` 逐中断转事件，卡片 id 的轮次取自 `interrupt_identity.announced_rounds(ctx.agent_input)`（swarm_fission 专路由） |
| `recovery/stream_recovery.py` | 主恢复策略组合（overflow/failover/escalation/retry/iteration-limit） |
| `recovery/stream_recovery_truncation.py` | max-token 续写、被截断或被扣留（参数不完整/无法解析）的 tool-call 重试 |
| `recovery/stream_recovery_oneshot.py` | THINKING_SIGNATURE / DUPLICATE_TOOL_USE_ID / IMAGE_TOO_LARGE / MEDIA_REJECTED / ALLOWED_TOOLS_TOOL_CHOICE_REJECTED / LONG_CONTEXT_TIER 等一次性恢复（支持单图超限收缩与多图累积超限历史轮次聚合降级保底，WebUI progress step: `thinking_signature_recovery`, `tool_history_recovery`, `image_shrink_recovery`, `long_context_tier_recovery`, `vision_fallback_recovery`, `media_rejected_recovery`, `allowed_tools_rejected_recovery`） |
| `recovery/stream_recovery_continuation.py` | steering、subagent 完成、goal continuation |
| `stream_compactor.py` | 高频流式文本片段合并缓冲（容量/时间/事件类型变更/显式 flush，后台看门狗防幽灵延迟） |
| `stream_buffer.py` | SSE 断线重连回复缓冲：内存滑动窗口 + GlobalStreamRegistry（Last-Event-ID 短断连复连，无磁盘持久化） |

### 并行中断与按卡片 id 作答

图可以同时在多个任务上挂起（并行子智能体各自等待审批）。LangGraph 为每个中断分配稳定 id，但它只取决于挂起它的任务（`xxh3_128(checkpoint_ns)`，重放时不变），不区分同一任务的第几次挂起：委派在每一步前都要审批、一个任务连续 `interrupt()` 三次时，三次挂起共用一个 id。有多个待决中断时，不带 id 的 resume 会被 LangGraph 拒绝（`When there are multiple pending interrupts, you must specify the interrupt id when resuming`）。

卡片 id（`interruptId`）因此是 `<LangGraph 中断 id>.<轮次>`，轮次 = 该任务已消费的答复数（LangGraph 以待写入通道 `__resume__` 的列表长度记录，`interrupt()` 用它决定返回已有答复还是再次挂起）。每次挂起各有各的卡片 id：同一任务的下一次挂起不会被客户端当作上一张卡的重复，上一张卡的答复也不会落到它上面。

- 轮次的来源：只在 resume 咽喉、运行开始前读一次（`_internals/resume_addressing.py` 读 `aget_state` 的待决中断与任务、`checkpointer.aget_tuple` 的 `__resume__`），经 `AddressedResume.announce_rounds` 交给分发器：被这次 resume 作答的中断为原轮次 +1，其余待决中断不变，运行中新出现的任务从 0 开始。运行中不读检查点：宣告新挂起的那一刻，它自己的待写入还没落盘，此时读到的是旧轮次（人为拖慢写盘 50 ms 的实测里，并行任务下第 1、2 轮分别被读成 0、1）。
- 发出：`interrupt_events.interrupt_events` 把一个 `__interrupt__` 分片里的每个中断转换为一个流事件，事件顶层带卡片 id。部分作答后图重新挂起，仍待决的中断会作为新分片再次发出（轮次不变），客户端按卡片 id 去重。resume 未经寻址（线程读不出）时轮次未知，事件不带卡片 id，客户端按无 id 处理。
- 作答：resume 载荷可携带 `interruptId`；`_internals/resume_addressing.address_resume_to_pending` 在 resume 咽喉只在「该中断待决且其任务已消费的答复数恰为卡片 id 的轮次」时把它改写为 `Command(resume={中断 id: 载荷})`。其余一律（已处理、轮次未到、不是 `<中断 id>.<轮次>` 的形状）改写为一个无人持有的合法中断 id，LangGraph 忽略它：答复不会送给任何人，运行回到真正待决的挂起上重新宣告，而不是把答复当成纯值交给别的挂起。
- 不带 id 的答复：待决 ≤1 个时原样透传（既有调用方行为不变）；待决 ≥2 个时，只有全局驳回（`{"decision": "reject"}` 且无 `decisions`，超时计时器所用）会广播给全部待决中断，其余答复（含批准）原样交给 LangGraph 拒绝——批准从不广播。
- 提示缓存：只有流事件与 resume 载荷变化，提示词与工具 schema 不变；`interruptId` 在咽喉处从答复里剥掉，不进入工具收到的值。

### 被扣留的工具调用与断流

适配层不会执行参数被截断或无法解析的工具调用，只把它记录在最终 AIMessage 的 `additional_kwargs["tool_call_recovery"]`（该消息没有 `tool_calls`，LangGraph 会据此结束整轮）。因此：

- `event_handlers.process_updates_chunk` 保留只记录被扣留调用的消息，恢复处理器才能看到它；
- `recovery/stream_recovery_truncation.py` 最多重试 1 次：丢弃该消息，在原请求后追加一条提示（提示缓存前缀不变），并一次性放大输出预算（有上限，不会低于已配置预算）；仍失败，或当前是 resume 轮（无法重放输入），则上报 `tool_call_truncated`；
- 流在收到最终元数据块之前断开时，`finish_reason` 记为 `__stream_dropped__`，`map_to_completion_status` 将其映射为 `truncated`，并禁止“补全 JSON”式修复；
- 上游在没有 `finish_reason` 时干净关闭，LiteLLM 流包装器会合成 `stop`，块层与正常结束完全相同，因此不会被记为断流（`finish_reason` 与遥测口径不变）。适配器改读包装器自己记录的提供方结束标记（`received_finish_reason` / `intermittent_finish_reason`，`StreamAggregator.provider_finish`）：两者都为空说明提供方没有结束这条流，工具参数不再补全，该调用按被扣留处理并走上面的重试；没有这两个标记的流（Responses 线路）仍只看 `finish_reason`。停在字符串内部的参数无论如何都拒绝执行（`litellm_utils.py` 的 `truncated_mid_value`）。

### 恢复重放与回复文本（重启契约）

恢复处理器（模型切换、溢出压缩、一次性恢复等）会让 `StreamExecutor` 重新驱动同一份 `agent_input`，并通过 STATUS 事件的顶层 `restart: true`（`MODEL_ESCALATED` 为 `data.restart: true`）告知消费者“在途段落将被重新流式输出”。仅给出提示、不重放的 STATUS（如备用模型未配置）不带该标记。

- 执行图带检查点（`thread_id` = session_key 或 message_id）：已完成的工具步骤随检查点保留，重放时模型从其后续写，工具不会重复执行，工具步骤之前的文本也不会重发。因此重启只作废“最近一次 `tool_start` 之后”的在途段落，而不是整条回复。
- Python 侧统一用 `answer_draft.AnswerDraft` 实现该规则（WebUI 前端在 `tool_start` 重置累积缓冲、遇重启丢弃草稿，结果等价）：`feed(event)` 累积 `message` 文本、在 `tool_start` 处标记段落起点、遇重启事件丢弃在途段落并返回文本是否变化；`restart()` 供调用方在别的通道得知同一次切换时显式调用（幂等）。拼装最终回复的消费者（子智能体执行器、IM 通道、定时任务、看板、评测、自动续跑、WebUI 持久化、OpenAI 兼容接口的非流式响应）都使用它；子智能体与主智能体跑在同一个 `StreamExecutor` 上，其结果（及失败时的 `partial_output`）是主模型读到的工具结果；语音播报与逐段下发的流式响应不使用——已朗读的音频、已发出的 SSE 增量无法收回。

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
