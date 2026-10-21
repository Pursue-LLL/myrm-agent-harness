# agent/security/single_use_tickets 架构说明

## 架构概览

一次性鉴权门票与三令牌链（DSH Data Agent §9）原子校验引擎。为敏感工具执行提供会话隔离、参数防篡改与阅后即焚的确定性安全门禁。

## 文件清单

| 文件 | 地位 | 职责 | I/O/P |
|------|------|------|-------|
| `__init__.py` | 核心 | 导出门票管理器、状态类型与摘要计算入口 | ✅ |
| `manager.py` | 核心 | 门票生命周期管理、规范化内容摘要与线程安全原子核销 | ✅ |
| `types.py` | 核心 | 门票数据结构定义、令牌类型枚举与状态流转模型 | ✅ |

## 模块依赖

- 内部依赖：`agent/security/single_use_tickets/types.py`
- 外部依赖：标准库 `hashlib`, `json`, `logging`, `threading`, `uuid`, `dataclasses`, `enum`, `time`
