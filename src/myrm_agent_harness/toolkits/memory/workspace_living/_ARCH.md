# Workspace Living 模块架构

工作区活文档同步与因果去重合并治理模块。
提供 Living ADR 架构决策状态与已知环境坑点（KNOWN_ISSUES.md）的原子幂等写入、因果特征签名计算与去重维护能力。

## 文件清单与职责

| 文件 | 地位 | 职责 | I/O/P |
| --- | --- | --- | --- |
| `__init__.py` | 模块入口 | 导出领域模型与去重合并器 | ✅ |
| `models.py` | 领域模型 | 定义 KnownIssueEntry、ADRMetadata、去噪因果签名生成算法 | ✅ |
| `merger.py` | 核心服务 | 提供 KNOWN_ISSUES.md 并发安全原子去重写入与自增更新 | ✅ |

## 模块依赖

- 仅依赖 Python 标准库（`asyncio`, `hashlib`, `os`, `re`, `tempfile`, `pathlib`, `datetime`），零外部三方强依赖。
- 作为纯粹的单机文件工具层，被 `agent.workspace_rules` 及相关记忆工具按需调用，绝无反向耦合。
