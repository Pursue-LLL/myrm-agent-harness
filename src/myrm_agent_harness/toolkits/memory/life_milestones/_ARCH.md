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
