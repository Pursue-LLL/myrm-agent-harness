# composite_usage_ledger/

## 架构概述

基于六维复合主键的任务级与模型级持久化分摊账本与双轨对账引擎包。上级文档：[../_ARCH.md](../_ARCH.md)。

彻底打破传统用量数据散落在各个会话的 JSONL event log 导致高开销磁盘全扫描以及无法拆分子任务成本的架构缺陷。通过六维复合主键声明：`(session_id, model, billing_provider, billing_base_url, billing_mode, task)`，实现精细化任务维度归因（如主对话 `main_turn`、工件编译 `artifact_compile`、后台审查 `background_review`、标题抽取 `title_gen`），结合本地阶梯价预估（`estimated_cost_usd`）与供应商真实回传扣费（`actual_cost_usd`）双轨核算与偏差漂移告警（>15% 偏差触发 `DISCREPANCY_ALERT`）。

## 文件清单

| 文件 | 地位 | 职责 | I/O/P |
|------|------|------|-------|
| `models.py` | 实体模型 | 六维复合主键、对账状态枚举、单条复合账本记录与聚合摘要数据契约 | ✅ |
| `ledger.py` | 核心引擎 | 线程安全复合用量账本、增量累加、发票回填对账、多维查询聚合与单例管理 | ✅ |
| `__init__.py` | 门面 | 聚合导出模块内所有数据模型与账本单例 | ✅ |
