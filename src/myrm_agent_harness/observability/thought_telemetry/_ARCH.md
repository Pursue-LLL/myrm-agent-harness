# observability/thought_telemetry/

## 架构概述

长推理思考链（CoT）流式遥测与失控死循环守护模块。直击长思考模型（o1 / DeepSeek-R1 / Claude 3.7 Extended Thinking）在隐蔽思维流中产生死循环复读、无序发散或过度燃烧 Token 的痛点。上级文档：[../_ARCH.md](../_ARCH.md)。

## 文件清单

| 文件 | 地位 | 职责 | I/O/P |
|------|------|------|-------|
| `__init__.py` | 门面 | 模块顶级符号导出与统一接口 | ✅ |
| `models.py` | 模型 | 思维流指标快照 (`ThoughtTelemetrySnapshot`)、失控原因枚举 (`RunawayReason`) 与思维步骤标记契约 (`ThoughtStepMarker`) | ✅ |
| `runaway_guard.py` | 核心 | 思维链死循环与发散失控熔断守卫 (`CoTRunawayGuard`)，基于滑动窗口 N-gram 重复率与预算上限触发软中断 | ✅ |
| `tracker.py` | 引擎 | 思维流实时遥测追踪器 (`ThoughtTelemetryTracker`)，计算毫秒耗时、Token 估算、自纠偏步骤特征识别与发散度评分 | ✅ |
