# ui_alignment/

## 架构概述

UI 视觉方案多轮渐进对齐、变体比选与自适应原型演进框架层核心引擎（Item 39 P0）。
彻底杜绝“盲目直接写代码导致界面难看不符合预期大面积返工”的痛点。
在 Plan 需求计划书确认后、正式写业务代码前，前置 UI 视觉方案多轮对齐、同屏比选与画布批注，最终固化为结构严密的 `VisualContract`。
上级文档：[../_ARCH.md](../_ARCH.md)。

## 文件清单

| 文件 | 地位 | 职责 | I/O/P |
|------|------|------|-------|
| `__init__.py` | 入口 | 门面导出引擎与领域模型 | ✅ |
| `models.py` | 契约 | `UiVariantStyle`、`UiVariant`、`VisualAnnotation` 与 `VisualContract` 核心数据模型 | ✅ |
| `alignment_engine.py` | 核心 | `UiDesignVisualAlignmentEngine` 变体池管理、画布批注汇聚与编译固化严密 `VisualContract` 强约束 Prompt | ✅ |

## 依赖

- 纯内存与字符串模板编译，零重载三方库依赖，纳秒级操作
