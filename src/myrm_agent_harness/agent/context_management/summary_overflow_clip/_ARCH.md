# summary_overflow_clip Architecture Documentation

## [POS]
所属模块：`myrm_agent_harness.agent.context_management.summary_overflow_clip`
核心职责：摘要辅助 LLM 调用上下文溢出尾段裁剪与单次重试防护套件，对尾部超大工具结果执行 read_file 头部切片与落盘 stub 替换，并严格锁存单次重试，防止压缩过程本身撑爆模型窗口引发死循环。

## 模块结构
| 文件 | 职责 |
|---|---|
| `overflow_clip_types.py` | 强类型契约、裁剪策略枚举、重试裁决枚举、裁剪动作与缩减结果模型 |
| `tail_message_clipper.py` | 尾段工具消息裁剪器，区分文件读取头部切片与通用工具落盘 stub 替换 |
| `overflow_retry_guard.py` | 单次重试防死循环守护器，严格单调递减校验与单次重试锁存熔断 |
| `summary_overflow_clip_suite.py` | 统一协调主门面 `SummaryCallOverflowTailClipRetrySuite` |
| `__init__.py` | 包级公共符号门面导出 |
