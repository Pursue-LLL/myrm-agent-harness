# packages/

## 架构概述

闭源分发辅助子项目根目录。当前仅含平台 core wheel 工程；构建逻辑见 [harness_packaging/_ARCH.md](../harness_packaging/_ARCH.md) 与 [DISTRIBUTION_SYSTEM.md](../harness_packaging/DISTRIBUTION_SYSTEM.md)。

## 目录清单

| 目录 | 地位 | 职责 |
|------|------|------|
| `myrm-agent-harness-core/` | 核心 | Nuitka 编译产物平台 wheel 工程（marker 包 + force-include `.so`）· [\_ARCH.md](myrm-agent-harness-core/_ARCH.md) |

## 模块依赖

- **构建入口**：`scripts/build_core.py`、`scripts/assemble_production.py`
- **SSOT**：`harness_packaging/core_manifest.yaml`
