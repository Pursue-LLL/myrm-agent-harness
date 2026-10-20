# toolkits/swarm 架构说明

---

## 模块定位

`swarm` 模块承载多智能体蜂群并发协同（Swarm Mode）、显式规则与偏好记忆自动唤醒（Recalled Rules HUD）、以及交付物人类负责人待核实风险清单（Owner Action & Risk Checklist）的执行引擎（Item 42 P0）。
直击 EvoX 桌面端极致交互精髓：
1. 支持将复杂任务一键激活平级多子 Agent 并行（默认 3~5 个配额），显式记录子 Agent 任务边界与当前步骤；
2. 捕获并维护从上轮会话唤醒的业务规则与偏好，支持动态微调与停用，并编译为强约束 `@active_rules` 提示词；
3. 结构化跟踪复杂方案末尾的人类店主/负责人核查风险项（如商圈噪音限制、物业电力、排班缺口等），提供确权与闭环能力。

---

## 文件清单

| 文件 | 地位 | 职责 |
|------|------|------|
| `models.py` | 契约 | 纯领域模型定义（`SwarmModeConfig`, `SwarmSubagentTask`, `RecalledRuleItem`, `OwnerRiskItem`, `RiskSeverityLevel`），零 `Any` |
| `swarm_engine.py` | 核心 | 线程安全协同引擎 `SwarmCoordinationEngine`，管理蜂群配置、子任务分发、规则唤醒/提示词编译、风险清单确权 |
| `__init__.py` | 门面 | 聚合导出模块符号 |
| `_ARCH.md` | 文档 | 模块定位与架构索引规范 |

---

## 依赖关系

- 纯 Python 3.13 标准库（`dataclasses`, `threading`, `time`, `typing`）
- 零第三方外部重依赖，零 `Any`
