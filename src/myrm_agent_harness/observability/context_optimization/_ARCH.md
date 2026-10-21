# context_optimization/

## 架构概述

上下文拦截节流审计器、跨工具 Token 节省率分析与工程信号七维决策套件。
针对智能体在会话执行中调用 Playwright、Bash、代码文件读取等工具时产生的巨量输出，审计通过截断、存根索引替换及 Prompt Cache 命中为用户节省的真实 Token 数量，按模型费率精准折算真金白银（USD/CNY），并从会话事件中挖掘 7 维工程决策信号（高频重试、输出膨胀、长耗时 I/O、缓存饥渴等），按 CTO、EM、FinOps、DevOps 四大角色提供针对性洞察。

上级架构：[../_ARCH.md](../_ARCH.md)。

## 文件清单

| 文件 | 地位 | 职责 | I/O/P |
|------|------|------|-------|
| `__init__.py` | 入口 | 模块门面导出 | ✅ |
| `models.py` | 数据模型 | `ToolSavingsRecord`、`SessionSavingsAudit`、`EngineeringSignalItem`、`RoleEngineeringInsightReport` 等不可变数据契约 | ✅ |
| `savings_auditor.py` | 核心引擎 | `ContextOptimizationSavingsAuditor`：单次工具拦截节流登记、多工具指标聚合、节约金额折算与会话战报生成 | ✅ |
| `signal_analyzer.py` | 分析引擎 | `EngineeringSignalAnalyzer`：7 维工程决策信号（重试死循环、输出膨胀、阻塞 I/O、缓存饥渴）识别与 4 角色视图定制报告生成 | ✅ |
