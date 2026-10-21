# failure_facts/

## Overview
子智能体脱敏结构化失败事实与安全归因诊断协议（Subagent Bounded Structured Failure Facts & Privacy-Preserving Diagnostic Protocol）：
对标 DeepSeek Harness 多模态更新（2026-08-18 产品规范），解决异步子智能体崩溃/超时报错过于模糊导致父任务盲目重试、或者过于暴露导致底层 API Key、绝对路径与私密 Payload 泄露给大模型的双重痛点。
提供标准化单行安全失败诊断头（Single-line Safe Diagnostic Header）、4096 字节严格有界准入门禁、六大精细化生命周期阶段（Stage）、九大确定性故障分类（Category）、敏感凭证自动安全脱敏器（SafeSanitizer）以及确定性自愈建议矩阵（RemediationStrategy）。

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Facade | 门面导出 `SubagentDiagnosticProtocol`、`SafeFailureSanitizer`、`StructuredFailureFact`、`SubagentFailureCategory`、`SubagentFailureStage` 与 `RemediationAction` | — |
| `types.py` | Core | 核心类型与枚举：生命周期阶段枚举 `SubagentFailureStage`、故障类别枚举 `SubagentFailureCategory`、自愈策略枚举 `RemediationAction` 与结构化失败事实不可变数据契约 `StructuredFailureFact` | ✅ |
| `sanitizer.py` | Core | 隐私与凭证安全脱敏引擎：针对 Bearer Token、sk-* 密钥、API Key、系统绝对路径、敏感环境变量等执行正则过滤替换，并执行严格 4096 字节 UTF-8 边界安全截断保护 | ✅ |
| `protocol.py` | Core | 单行安全诊断协议与智能归因器：格式化标准诊断头 `Product subagent failure (...)`、从状态码/退出码/信号/异常文本推导故障类别，并推导可操作的自愈策略 | ✅ |
