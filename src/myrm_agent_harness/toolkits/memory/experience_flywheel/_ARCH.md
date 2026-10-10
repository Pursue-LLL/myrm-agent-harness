# Project Experience & ADR Flywheel Architecture (`experience_flywheel`)

## 1. 架构定位
本模块实现路线图 Item 154 `ProjectExperienceAndADRFlywheelSuite`，对标 GBrain 工业级知识飞轮实践，提供工程任务执行失败与测试重试中的踩坑经验（Bug Experience）及架构决策（ADR）自动提取器、因果实体绑定存储引擎（`CausalFlywheelStore`），以及在后续任务规划阶段主动嗅探雷区并拦截重复犯错的嗅探守卫（`MinefieldPreSniffingGuard`），并与四维记忆 U 盘协议（`project_dongle`）实现自闭环双向沉淀。

## 2. 模块文件表
| 文件 | 职责 |
|---|---|
| `models.py` | 核心域模型（`ExperienceKind`, `EngineeringExperience`, `MinefieldAlert`, `FlywheelIngestResult`） |
| `extractor.py` | 踩坑经验与架构决策三元组/四元组抽取器（`BugExperienceAndADRExtractor`） |
| `flywheel_store.py` | 因果关系固化入库、实体索引与四维 U 盘记忆同步存储（`CausalFlywheelStore`） |
| `minefield_guard.py` | 历史雷区前置嗅探与主动拦截预警顾问（`MinefieldPreSniffingGuard`） |
| `__init__.py` | 包门面导出 |
