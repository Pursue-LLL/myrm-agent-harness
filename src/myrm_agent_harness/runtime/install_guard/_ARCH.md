# install_guard/

## 概述

双 wheel 闭源分发的 **运行时安装门禁**：manifest codegen 目标、源码/编译模式探测、platform key 校验、安装后 verify CLI。

归属 `runtime/` 层 — 与 `doctor.py` 并列，回答「这个环境能否跑 Harness / Agent」。

## 文件

| 文件 | 地位 | 职责 | I/O/P |
| --- | --- | --- | --- |
| `__init__.py` | 门面 | Re-export `DistributionMode`、`assert_distribution_ready` 等 | ✅ |
| `probe.py` | 核心 | `source` / `compiled` / `incomplete` 探测 + fail-closed 校验（含 `unknown` platform key 拒绝） | ✅ |
| `platform.py` | 核心 | **生成文件** — `harness_packaging/platform_key.py` → 运行时 platform key | — |
| `verify.py` | 核心 | Console script `verify-harness-distribution` 入口 | ✅ |
| `_generated/core_ip_manifest.py` | 核心 | **生成文件** — YAML manifest → import 路径 SSOT | — |

## 依赖

- 父模块 [`../_ARCH.md`](../_ARCH.md)
- `harness_packaging/codegen.py`（build-time 写入 `_generated/core_ip_manifest.py` 与 `platform.py`）
- 详见 [`../../../../harness_packaging/DISTRIBUTION_SYSTEM.md`](../../../../harness_packaging/DISTRIBUTION_SYSTEM.md)
