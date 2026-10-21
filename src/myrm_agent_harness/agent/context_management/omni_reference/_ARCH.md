# omni_reference 模块

## 架构概述

全域多维上下文引用与动态切片提取引擎。提供针对五维目标（`@file:`, `@session:`, `@artifact:`, `@agent:`, `@task:`）的引用语法解析、防上下文膨胀的安全切片生成以及规范的不可降解 Prompt 注入格式化。

上级文档：[../_ARCH.md](../_ARCH.md)。

---

## 文件清单

| 文件 | 地位 | 职责 | I/O/P |
|------|------|------|-------|
| `slice_extractor.py` | 核心 | `OmniReferenceExtractor` — 语法解析、字符上限截断保护与 `format_omni_context_slices` Prompt 注入格式化 | ✅ |
| `__init__.py` | 门面 | 对外 re-export 公共 API | ✅ |

---

## 依赖关系

- 纯 Python 实现，零外部重型依赖，完全独立于业务层。
