# Streaming Execution & Recovery Architecture

## 架构概述

提供流式中断安全捕获、最长公共前缀（LCP）动态去重清洗、思考与升级标签脱毒、高频事件压实与无缝断点续接引导能力。

## 文件清单

| 文件 | 地位 | 职责 |
| --- | --- | --- |
| `__init__.py` | 入口 | 模块导出与公共流式事件接口定义 |
| `artifact_events.py` | 核心 | 工件事件处理（文件工件、UI工件、内联图片工件与实时内容更新） |
| `channel_output_hints.py` | 核心 | 交付渠道输出格式提示词生成（Channel-Aware Output Guidance）与前置提示保障 |
| `citation_audit.py` | 核心 | 流式回复引用标记审计（【N】序号与信息源对照验证） |
| `escalation_scrubber.py` | 核心 | 模型自主升级标记（`<<<NEEDS_PRO>>>`）流式拦截与重试恢复触发 |
| `event_handlers.py` | 核心 | LangGraph updates/messages 流式事件向业务事件转换与图片事件分发 |
| `message_builder.py` | 核心 | 原始用户输入向 LangChain 消息结构转换与时间戳就地注入 |
| `model_discipline.py` | 核心 | 模型执行纪律与模型家族行为调优提示词体系（层级化 Tool 引导与反幻觉） |
| `reasoning_scrubber.py` | 核心 | 模型思考推理标签（`<think>`等）状态机清洗与独立事件重定向 |
| `repetition_scrubber.py` | 核心 | 模型退化重复循环实时检测与流式熔断保护 |
| `resume_checkpoint.py` | 核心 | 流式安全断点抓取、字符级去重清洗、Prompt 缓存无损续传引导词生成 |
| `run_digest.py` | 核心 | 智能体实时执行快照 DTO 与步骤信息归纳聚合器 |
| `source_tracker.py` | 核心 | 会话级引用信息源追踪、全局去重编号与增量分发 |
| `step_builder.py` | 核心 | 智能体步骤执行数据格式化（面向 WebUI 的多类型工具状态渲染契约） |
| `stream_buffer.py` | 核心 | 内存滑动窗口流式重放缓冲与 Last-Event-ID 重连恢复 |
| `stream_compactor.py` | 核心 | 高频文本片段流式合并压实器（降低前端事件风暴与渲染开销） |
| `stream_dispatcher.py` | 核心 | 流式执行引擎事件分发 Mixin 与 AgentStatus 状态机透传 |
| `stream_executor.py` | 核心 | 流式执行引擎生命周期封装（Agent.astream 调度、重试恢复与异常拦截） |
| `types.py` | 核心 | 流式事件类型定义与 core.events.types 兼容重导出 |
| `utils.py` | 辅助 | 时间戳规则、时区管理上下文变量及工具名称规范化等通用辅助函数 |
