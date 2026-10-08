# LifeMilestonesAndPersonalTimelineEngineSuite Architecture Contract

## 1. 模块定位与职责边界
- **定位**：属于 `myrm_agent_harness.toolkits.memory` 核心框架扩展套件，负责用户宏观人生大事年表建模、价值观时序因果演进时间轴以及非功利性成长日记自省卡片沉淀。
- **职责**：
  1. 长期实体时间轴建模：独立于日常短期任务执行流，承载跨越数十年的人生地标（求学、换城、婚育、亲友大事、重大抉择）；
  2. 价值观时序因果演进：支持非单调价值观蜕变谱系，杜绝精神分裂，为深层决策对话注入具备生命脉络与温度的 Prompt 投影；
  3. 成长日记自省沉淀：聚合非功利性心境感悟，生成结构化人生阶段自省卡片；
  4. 显著性门禁与敏感隔离：三级隐私防护（`OPEN_OVERVIEW`, `INTIMATE_PERSONAL`, `CONFIDENTIAL_RESTRICTED`）与工业琐事杂讯过滤门禁。
- **边界约束**：
  - 严禁包含 Web/HTTP 或特定数据库绑定，纯内存与通用领域数据结构设计；
  - 严禁将敏感私密数据注入普通代码/工具调用环境；
  - 严禁使用 `Any` 类型，必须全面使用精确 Type Hints。

## 2. 文件清单

| 文件 | 角色 | 职责 | I/O/P |
| --- | --- | --- | --- |
| `models.py` | 实体模型 | 三级隐私枚举、里程碑类别与记录、价值观节点、成长日记、人生阶段、回顾卡片与上下文投影载荷 | ✅ |
| `significance_gate.py` | 准入门禁 | `MilestoneSignificanceGate`：拒绝过短标题与工业琐事文本，按关键词、类别与显式输入加权，得分达到阈值（默认 0.70）才准入 | ✅ |
| `timeline_engine.py` | 时间轴引擎 | `LifeMilestonesEngine`：经门禁录入里程碑，按类别、年份与隐私上限列出，提取转折点，管理人生阶段 | ✅ |
| `value_alignment_projector.py` | 价值观投影 | `ValueSystemAlignmentProjector`：价值观登记与演进（旧立场归档），识别深度人生意图并生成 Prompt 投影 | ✅ |
| `retrospective_aggregator.py` | 回顾聚合 | `GrowthRetrospectiveAggregator`：成长日记存取与人生阶段回顾卡片生成 | ✅ |
| `facade.py` | 门面 | `LifeMilestonesSuite`：组装上述组件的统一入口，并提供四项计数统计 | ✅ |
| `__init__.py` | 包门面 | 导出门面、引擎与数据模型 | ✅ |

## 3. 依赖关系

- 仅依赖 `pydantic` 与标准库；包内依赖方向为 `models` ← `significance_gate` ← `timeline_engine` ← `value_alignment_projector` ← `retrospective_aggregator` ← `facade`。
- 经 `myrm_agent_harness.toolkits.memory` 重新导出，被 `myrm-agent-server/app/services/memory/life_milestones/` 消费。
