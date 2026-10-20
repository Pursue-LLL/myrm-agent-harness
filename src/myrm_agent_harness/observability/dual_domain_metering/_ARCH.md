# dual_domain_metering/

## Overview
双域透明计量边界界定、平台交互与沙箱执行穿透式成本核算套件 (Dual-Domain Metering Boundary & Sandbox Cost Attribution Suite)。
彻底界定【管控网关域（Gateway Domain）】与【沙箱执行域（Sandbox Domain）】的计量边界，穿透统计模型 Token 消耗、沙箱容器算力租约与第三方扩展工具成本，支持生成防篡改 SHA-256 财务合规对账凭证。

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package Facade | 导出计量域枚举、三维成本、双域明细记录、对账单模型及账本单例工厂 | ✅ |
| `models.py` | Models | MeteringDomain, ThreeDimensionalCost, DomainMeteringRecord, SessionDualDomainSummary, ReconciliationStatement 强类型模型 | ✅ |
| `ledger.py` | Engine | 线程安全双域分轨账本、三维成本穿透聚合与 SHA-256 防篡改对账凭证生成器 | ✅ |
