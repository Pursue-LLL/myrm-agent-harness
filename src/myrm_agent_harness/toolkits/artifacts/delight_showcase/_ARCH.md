# toolkits/artifacts/delight_showcase 模块架构

---

## 架构概述

小白零门槛趣味创意灵感工坊与单文件自包含即席沙箱展示台框架层核心（Item 40 P0）。
负责定义趣味模板领域实体（DelightTemplate）、单文件即席沙箱契约（SingleFileSandboxContract），并提供纯净自包含单文件代码校验与包装引擎（SingleFileSandboxEngine），自动注入移动端视口 meta、全屏自适应与无依赖运行保障。

---

## 文件清单

| 文件 | 地位 | 职责 |
|------|------|------|
| `models.py` | 实体 | 领域模型：DelightCategory、DelightTemplate、SingleFileSandboxContract、SandboxValidationResult |
| `showcase_engine.py` | 引擎 | `SingleFileSandboxEngine` 校验单文件代码自包含性、检测 Canvas/Audio/Tailwind、包装完整 HTML 与视口保护 |
| `__init__.py` | 门面 | 聚合导出模块内模型与核心引擎 |
| `_ARCH.md` | 文档 | 模块架构描述与文件清单 |

---

## 依赖关系

- 纯标准库（re, uuid, time, dataclasses），零外部依赖，框架轻量通用。
