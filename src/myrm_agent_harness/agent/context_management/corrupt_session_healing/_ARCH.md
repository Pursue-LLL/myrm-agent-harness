# corrupt_session_healing Architecture Documentation

## [POS]
所属模块：`myrm_agent_harness.agent.context_management.corrupt_session_healing`
核心职责：损坏会话持久化存储优雅降级、异常反序列化收容隔离、部分有效转录救捞与零白屏新鲜会话平滑自愈套件。

## 模块结构
| 文件 | 职责 |
|---|---|
| `healing_types.py` | 强类型契约、恢复状态枚举、归档记录与自愈结果结构定义 |
| `corrupt_record_sandbox.py` | 损坏会话快照隔离与归档沙箱，记录诊断日志与指纹防污染 |
| `partial_transcript_salvager.py` | 损坏/截断快照部分有效消息打捞器，从损坏 payload 中挽救前序对话历史 |
| `fresh_session_auto_healer.py` | 零白屏新鲜自愈会话派生器，注入优雅降级上下文并保证交互不中断 |
| `corrupt_session_healing_suite.py` | 统一协调主门面 `CorruptSessionStorageGracefulDegradationAndAutoHealingSuite` |
| `__init__.py` | 包级公共符号门面导出 |
