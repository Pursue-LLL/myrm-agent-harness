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
- utils: 内部工具函数（上下文验证、时间基准常量、工具名称规范化）
"""
