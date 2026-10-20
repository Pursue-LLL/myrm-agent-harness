# org_spend_limit/

## 架构概述

团队共享智能体组织月度限额、逐 Query 标签归因与超限熔断套件。
针对团队协同（群聊/频道 Channel）与私信（DM）混合调用场景，实现“群内协同记入组织公摊账本，私聊记入个人账户”的分级归因契约。提供组织月度预算配置、80% 水位软预警与 100% 硬限额熔断刹车，并支持按 `ident:<user_id>` 身份命名空间与调用 Surface（CHANNEL/DM/REST_API/AUTOMATED_CI）对账穿透。

上级架构：[../_ARCH.md](../_ARCH.md)。

## 文件清单

| 文件 | 地位 | 职责 | I/O/P |
|------|------|------|-------|
| `__init__.py` | 入口 | 模块门面导出 | ✅ |
| `models.py` | 数据契约 | `BillingScope`、`SpendSurface`、`GovernorAction`、`QuerySpendLabel`、`SpendLimitConfig`、`SpendGovernorDecision`、`IdentSpendAttribution` 等不可变契约定义 | ✅ |
| `spend_governor.py` | 核心引擎 | `OrgSharedAgentSpendGovernor`：组织月度预算治理、调用前限额预检阻断、真实支出与标签绑定上报，以及按身份/Surface 聚合归因 | ✅ |
