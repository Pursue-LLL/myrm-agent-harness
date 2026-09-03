# _generated/

## 概述

编译分发/打包时自动生成的 Core IP Manifest 映射包。

## 文件

| 文件 | 地位 | 职责 | I/O/P |
| --- | --- | --- | --- |
| `__init__.py` | 门面 | 自动生成包入口声明 | — |
| `core_ip_manifest.py` | 核心 | 自动生成的 Core IP 闭源模块清单与 import 路径 SSOT | — |

## 依赖

- 由 `harness_packaging/codegen.py` 构建时写入
