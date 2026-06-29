# myrm-agent-harness 模块架构

## 架构概述

闭源 Agent 执行引擎（PyPI 包 `myrm-agent-harness`）。**GUI-first 通用 AI 工作助手 harness**（WebUI / Tauri / 云沙箱），框架层与业务解耦，供 `myrm-agent-server` 通过 `uv.lock` 消费。整体架构、模块导航与依赖关系见 **[ARCHITECTURE.md](ARCHITECTURE.md)**；框架设计原则见 **[FRAMEWORK_DESIGN_PRINCIPLES.md](FRAMEWORK_DESIGN_PRINCIPLES.md)**。

## 根目录文件

| 文件 | 职责 |
|------|------|
| `ARCHITECTURE.md` | L1：整体架构、模块导航、文档索引 |
| `FRAMEWORK_DESIGN_PRINCIPLES.md` | 框架设计原则与边界约束 |
| `pyproject.toml` / `uv.lock` | 包元数据与依赖锁 |
| `LICENSE` | Proprietary 许可 |
| `README.md` | PyPI / GitHub 入口（安装与快速开始） |
| `_ARCH.md` | 本文件：子目录职责表 |

## 目录清单

| 目录 | 地位 | 职责 |
|------|------|------|
| `src/myrm_agent_harness/` | 核心 | 框架源码（agent、toolkits、runtime、api 等）· [\_ARCH.md](src/myrm_agent_harness/_ARCH.md) |
| `harness_packaging/` | 核心 | 闭源分发：Nuitka 编译、wheel 组装 · [\_ARCH.md](harness_packaging/_ARCH.md) |
| `tests/` | 辅助 | 单元 / 集成 / API 冒烟 · [\_ARCH.md](tests/_ARCH.md) |
| `benchmarks/` | 辅助 | CI 性能回归；`archive/` 存历史脚本 · [\_ARCH.md](benchmarks/_ARCH.md) |
| `scripts/` | 辅助 | 边界检测、PyPI 发布、tool registry、分形 `_ARCH` 门禁 · [\_ARCH.md](scripts/_ARCH.md) |
| `packages/` | 辅助 | 平台 core wheel 子工程 · [\_ARCH.md](packages/_ARCH.md) |

## 模块依赖

- **被依赖方**：`myrm-agent/myrm-agent-server`（业务编排，仅 import `myrm_agent_harness.api` 等公开路径）
- **构建**：tag `v*` → CI 发 PyPI → vortexai `./myrm harness sync-lock` 刷新 OSS `uv.lock`

## 约束

- 框架层禁止 import `app.*` 或任何 server 业务模块
- 公开 API 变更须同步 `tests/api/` 与 [DISTRIBUTION_SYSTEM.md](harness_packaging/DISTRIBUTION_SYSTEM.md)
- 性能基准仅放在 `benchmarks/`，禁止在 vortexai 开发壳根目录创建 `benchmarks/`
