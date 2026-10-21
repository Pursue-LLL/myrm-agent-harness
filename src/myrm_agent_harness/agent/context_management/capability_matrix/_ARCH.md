# capability_matrix/

## 架构概述

情境感知型渐进式能力即时推荐与交互式快捷指令全景面板核心引擎（Item 38 P0）。
直击系统功能深度极高却「藏得太深、用户根本不知道有这功能」的学习曲线痛点。
上级文档：[../_ARCH.md](../_ARCH.md)。

## 文件清单

| 文件 | 地位 | 职责 | I/O/P |
|------|------|------|-------|
| `__init__.py` | 入口 | 门面导出引擎与领域模型 | ✅ |
| `models.py` | 契约 | `CommandCategory`、`CommandMatrixEntry`、`ContextStateSnapshot` 与 `CapabilityHintChip` 数据模型 | ✅ |
| `engine.py` | 核心 | `CapabilityDiscoveryEngine` 情境感知推断引擎，按执行态（耗时/数据/多步）启发式产出加权推荐芯片并自动剔除已掌握能力 | ✅ |

## 依赖

- 纯函数式与内存启发式评估，零外部网络与 I/O 依赖
