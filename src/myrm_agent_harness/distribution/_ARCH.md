# distribution/

## 概述

双 wheel 分发子系统：manifest _codegen_、源码/编译模式探测、平台 key 校验、安装后 verify CLI。

## 文件

| 文件 | 地位 | 职责 | I/O/P |
| --- | --- | --- | --- |
| `__init__.py` | 门面 | Re-export `DistributionMode`、`assert_distribution_ready` 等 | ✅ |
| `core_ip_manifest.py` | 核心 | **生成文件** — YAML manifest → import 路径 SSOT | — |
| `probe.py` | 核心 | `source` / `compiled` / `incomplete` 探测 + fail-closed 校验 | ✅ |
| `runtime_platform.py` | 核心 | 运行时 platform key（须与 `harness_packaging.runtime_platform` 一致） | ✅ |
| `verify.py` | 核心 | Console script `verify-harness-distribution` 入口 | ✅ |

## 依赖

- 父模块 [`../_ARCH.md`](../_ARCH.md)
- `harness_packaging/codegen.py`（build-time 写入 `core_ip_manifest.py`）
- 详见 [`../../../harness_packaging/DISTRIBUTION_SYSTEM.md`](../../../harness_packaging/DISTRIBUTION_SYSTEM.md)

## 包根 Rule 5

包根允许 `__init__.py`、`client.py`（SDK 门面）、`py.typed`；本目录承载分发域全部实现模块。
