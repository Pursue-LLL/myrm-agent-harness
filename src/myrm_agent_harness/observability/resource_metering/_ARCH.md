# observability/resource_metering/

## 架构概述

混合算力对账与物理硬件/Token 资源计量引擎，对标火山方舟 Agent Plan AFP (Ark Feature Points) 双轨明细对账体系。提供沙箱容器物理执行秒数、规格加权与磁盘 Volume 吞吐折算，结合模型认知 Prompt/Completion/Caching Token 计算，生成统一算力对账单，并支持单任务资源上限防失控熔断。上级文档：[../_ARCH.md](../_ARCH.md)。

## 文件清单

| 文件 | 地位 | 职责 | I/O/P |
|------|------|------|-------|
| `models.py` | 模型 | 硬件资源占用 HardwareUsage、认知 Token 消耗 CognitiveUsage 与对账单快照 HybridLedgerReport | ✅ |
| `ledger.py` | 引擎 | 双轨积分折算引擎 ResourceMeteringLedger 与多维预算熔断器 BudgetCircuitBreaker | ✅ |
| `__init__.py` | 门面 | 模块对外符号统一导出 | ✅ |
