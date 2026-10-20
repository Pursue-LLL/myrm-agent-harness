# observability/coordination_friction/

## Overview
人机协调摩擦度量、人工监督衰减曲线与协同效率 ROI 量化记分板引擎（Human Coordination Friction & Supervision Decay Suite）。
负责对多智能体执行过程中人类在环干预（HITL 审批门禁、中途插嘴纠偏、结果打回重做、参数强行覆盖）进行结构化追踪，建立同一类任务模板随经验沉淀的人工介入衰减曲线（Supervision Decay Curve），并量化输出为团队净节省的人机协调耗时与真实业务 ROI 记分板。

## File & Module Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package Facade | 聚合导出人机摩擦度量数据模型与跟踪器。 | ✅ |
| `models.py` | Data Contracts | 定义 `InterventionType`、`TaskFrictionRecord`、`SupervisionDecayPoint` 与 `CoordinationScoreboardSummary` 强类型契约。 | ✅ |
| `friction_tracker.py` | Core Engine | 实现 `CoordinationFrictionTracker`，计算分模板/全局人机介入密度、重做率、衰减曲线与节省协调工时。 | ✅ |

## Architectural Constraints
1. **零 Any 类型**：严格采用 Python 强类型与不可变 dataclass 契约。
2. **第一性原理指标**：破除“堆砌拉起了多少个 Agent”的虚荣指标，把“人工介入点是否真正减少”、“重做率是否下降”、“净节省了多少注意力时间”作为核心量化标尺。
