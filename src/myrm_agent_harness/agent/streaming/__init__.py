"""BaseAgent event processing pipeline.

将 LangGraph 底层流事件转换为业务层可消费的事件。
此包为 BaseAgent.run() 的内部实现，不属于公开 API。

组件：
- message_builder: 消息准备与时间戳注入（build_messages / inject_datetime_tags）
- stream_executor: 流式执行引擎（StreamContext / StreamExecutor / _emergency_compact）
- event_handlers: LangGraph 流事件处理
- artifact_events: Artifact 事件处理（文件工件、UI 工件、实时内容）
- source_tracker: 引用源去重与编号
- step_builder: 前端步骤事件构建
- model_discipline: Per-model 执行纪律（模型感知的行为规则注入）
- channel_output_hints: 通道级输出格式提示（与 model_discipline 对称）
- stream_dispatcher: astream chunk 分发至 output_queue（redirect 局部文本保留 / swarm_fission 路由）
- stream_buffer: SSE 断连复连 replay buffer（内存滑动窗口 + GlobalStreamRegistry，无磁盘持久化）
- stream_compactor: 高频文本片段合并缓冲（后台看门狗防幽灵延迟）
- reasoning_scrubber: 流式推理内容清洗（非标准模型思考标签无损转独立事件）
- escalation_scrubber: 模型自升级标记（NEEDS_PRO）清洗与缓冲
- run_digest: RunDigest DTO + 纯函数聚合（progress-step → digest）
- types: 流事件数据类型与枚举（含 TOOL_IMAGE_OUTPUT）
- utils: 内部工具函数（上下文验证、时间基准常量、工具名称规范化）

子模块：
- broadcast: ToolBroadcastBus 进程内 side-channel pub-sub
- recovery: 流式错误恢复策略（overflow / failover / truncation / steering / continuation）
"""
