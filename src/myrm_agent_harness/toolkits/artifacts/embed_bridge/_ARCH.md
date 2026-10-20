# toolkits/artifacts/embed_bridge 模块架构

---

## 架构概述

轻量级可嵌入式业务挂件与宿主页面上下文双向注入协议框架层核心（Item 41 P1）。
负责定义挂件呈现模式（WidgetDisplayMode）、宿主上下文快照（HostContextSnapshot）、安全策略（EmbedSecurityPolicy）与注入结果（BridgeInjectedContext），并提供跨源 Origin 白名单校验与 `@host_context` 结构化 Prompt 编译注入引擎（HostContextBridgeEngine）。

---

## 文件清单

| 文件 | 地位 | 职责 |
|------|------|------|
| `models.py` | 实体 | 领域模型：WidgetDisplayMode、HostContextSnapshot、HostBridgeMessage、EmbedSecurityPolicy、BridgeInjectedContext |
| `bridge_engine.py` | 引擎 | `HostContextBridgeEngine` 负责 Origin 校验、编译 `@host_context` 结构化提示词并记录会话上下文 |
| `__init__.py` | 门面 | 聚合导出模块内模型与核心引擎 |
| `_ARCH.md` | 文档 | 模块架构描述与文件清单 |

---

## 依赖关系

- 纯标准库（urllib.parse, time, threading, dataclasses），零外部依赖，框架轻量通用。
