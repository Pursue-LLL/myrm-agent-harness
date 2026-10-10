# Cross-Source Work Context Fabric & Project Entity Linker Architecture (`context_fabric`)

## 1. 架构定位
本模块实现路线图 Item 153 `CrossSourceWorkContextFabricAndProjectEntityLinkerSuite`，提供多源非结构化工作流事件（飞书/钉钉/Linear/本地访谈文件/日程）的上下文织网引擎、实体/责任人/承诺/阻塞点提取器、活跃项目动态实体链接器，以及业务洞察结论向项目记忆块的反向自动沉淀与溯源回写闭环。

## 2. 模块文件表
| 文件 | 职责 |
|---|---|
| `models.py` | 核心域模型（`SourceKind`, `WorkEvent`, `WorkContextEntity`, `ProjectRegistryEntry`, `EntityMatchResult`, `InsightCandidate`, `InsightSinkRecord`） |
| `extractor.py` | 非结构化工作事件实体、责任人、承诺与阻塞点抽取器（`ContextFabricExtractor`） |
| `linker.py` | 活跃项目动态实体链接器与置信度归因打标（`ProjectEntityLinker`） |
| `sink.py` | 跨源结论自动沉淀、溯源打标与工作区记忆回写闭环引擎（`InsightSinkEngine`） |
| `__init__.py` | 包门面导出 |
