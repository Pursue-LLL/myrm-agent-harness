# observability/labor_acceleration/

## 架构概述

白领劳务效能加速度量化与生产力 ROI 计量引擎，对标 Nous Research 官方“Accelerate your labor with Hermes Agent”核心生产力量化主张。通过高频白领任务行为（网络检索、跨文档抽取、代码沙箱排障、专业邮件撰写与复杂逻辑推理）人工工时等效置换矩阵，量化单任务端到端加速倍率（如 96×）、累计挽回工时与算力投放 ROI，将冰冷的计算开销转化为透明、可感知的人类生产力跃迁指标。上级文档：[../_ARCH.md](../_ARCH.md)。

## 文件清单

| 文件 | 地位 | 职责 | I/O/P |
|------|------|------|-------|
| `models.py` | 模型 | 任务行为枚举 TaskActionType、工时置换明细 LaborEquivalencyItem 与综合评估快照 LaborAccelerationSummary | ✅ |
| `calculator.py` | 引擎 | 等效工时换算矩阵、加速倍率计算与生产力商业价值及 ROI 评估器 | ✅ |
| `__init__.py` | 门面 | 模块对外符号统一导出 | ✅ |
