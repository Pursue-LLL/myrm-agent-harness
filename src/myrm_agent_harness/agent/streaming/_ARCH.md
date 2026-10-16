# Streaming Execution & Recovery Architecture

## 架构概述

提供流式事件转换与分发、思考与升级标签脱毒、重复循环熔断、高频事件压实、Last-Event-ID 重连重放缓冲，以及流式错误的重试与恢复能力。详细设计见 [STREAMING_SYSTEM.md](STREAMING_SYSTEM.md)。

## 文件清单

| 文件 | 地位 | 职责 |
| --- | --- | --- |
| `__init__.py` | 入口 | 包入口（不再导出符号，调用方按模块路径导入） |
| `answer_draft.py` | 核心 | 流式回复文本累积器 `AnswerDraft` 与重启契约判定 `is_answer_restart`：恢复重放时只丢弃“最近一次 `tool_start` 之后”的在途段落（已完成的工具步骤由检查点保留，模型从其后续写，之前的文本不会重发）；所有从 `process_stream` 事件拼最终回复的消费者统一使用，禁止各自重写该规则 |
| `artifact_events.py` | 核心 | 工件事件处理（文件工件、UI工件、内联图片工件与实时内容更新） |
| `channel_output_hints.py` | 核心 | 交付渠道输出格式提示词生成（Channel-Aware Output Guidance）与前置提示保障 |
| `citation_audit.py` | 核心 | 流式回复引用标记审计（【N】序号与信息源对照验证） |
| `escalation_scrubber.py` | 核心 | 模型自主升级标记（`<<<NEEDS_PRO>>>`）流式拦截与重试恢复触发 |
| `event_handlers.py` | 核心 | LangGraph updates/messages 流式事件向业务事件转换与图片事件分发。错误事件经 `_error_category_value` 归一化 `ToolErrorCategory`：**必须取 `.value`**（该枚举是裸 `str` mixin，`str()` 会渲染成 `'ToolErrorCategory.ESTOP'`），否则 SSE 契约泄漏 Python 类路径、且 `classify_tool_fault_side` 因表内是值形字符串而全部失配退化为 `unknown`。只记录“被扣留工具调用”的 AIMessage（无 content、无 `tool_calls`，但 `additional_kwargs["tool_call_recovery"]` 含 `safe=False`）必须保留在 `collected_messages`：LangGraph 以末条无 `tool_calls` 的 AIMessage 结束整轮，若按“空消息”丢弃，恢复处理器就看不到这次失败的工具调用，整轮静默结束 |
| `interrupt_events.py` | 核心 | LangGraph `__interrupt__` 分片 → 流事件：每个中断一个事件，顶层带 `interruptId`（并行子 agent 各自挂起时，每张审批卡片可单独作答；resume 侧见 `_internals/resume_addressing.py`） |
| `message_builder.py` | 核心 | 原始用户输入向 LangChain 消息结构转换与时间戳就地注入 |
| `model_discipline.py` | 核心 | 模型执行纪律与模型家族行为调优提示词体系（层级化 Tool 引导与反幻觉） |
| `reasoning_scrubber.py` | 核心 | 模型思考推理标签（`<think>`等）状态机清洗与独立事件重定向 |
| `repetition_scrubber.py` | 核心 | 模型退化重复循环实时检测与流式熔断保护 |
| `run_digest.py` | 核心 | 智能体实时执行快照 DTO 与步骤信息归纳聚合器 |
| `source_tracker.py` | 核心 | 会话级引用信息源追踪、全局去重编号与增量分发 |
| `step_builder.py` | 核心 | 智能体步骤执行数据格式化（面向 WebUI 的多类型工具状态渲染契约） |
| `stream_buffer.py` | 核心 | 内存滑动窗口流式重放缓冲与 Last-Event-ID 重连恢复 |
| `stream_compactor.py` | 核心 | 高频文本片段流式合并压实器（降低前端事件风暴与渲染开销） |
| `stream_dispatcher.py` | 核心 | 流式执行引擎事件分发 Mixin（覆盖 Tool Stdout、UI 更新、任务步骤、AgentStatus 状态机透传、ASYNC_USER_MESSAGE 异步通报分发与 `__interrupt__` 分片分发——中断转事件见 `interrupt_events.py`） |
| `stream_executor.py` | 核心 | 流式执行引擎生命周期封装（Agent.astream 调度、重试恢复与异常拦截） |
| `types.py` | 核心 | 流式事件类型定义与 core.events.types 兼容重导出 |
| `utils.py` | 辅助 | 时间戳规则、时区管理上下文变量及工具名称规范化等通用辅助函数 |
| `zero_replay/` | 子包 | 零事件重放前后端无缝重连协议核心引擎（单次原子快照基线 + 纯实时增量流门禁过滤）。参见 [zero_replay/_ARCH.md](zero_replay/_ARCH.md) |
