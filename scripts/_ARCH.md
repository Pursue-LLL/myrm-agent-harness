# scripts/ 模块架构

## 架构概述

Harness 仓维护脚本：框架-业务边界 enforcement、PyPI 发布校验、compiled-core 构建与 tool registry 校验。详见 [ARCHITECTURE.md](../ARCHITECTURE.md)。

## 文件清单

| 文件 | 地位 | 职责 | I/O/P |
| --- | --- | --- | --- |
| `boundary_check.py` | 核心 | CLI：全量/增量扫描 `src/myrm_agent_harness/` 非法跨层 import | ✅ |
| `boundary_config.py` | 核心 | 白名单前缀、禁止前缀、允许路径配置 | ✅ |
| `boundary_engine.py` | 核心 | AST 静态/动态 import 检测引擎 | ✅ |
| `build_core.py` | 核心 | compiled-core 构建入口 | ✅ |
| `build_release_wheel.py` | 核心 | 发布 wheel 组装 | ✅ |
| `assemble_production.py` | 辅助 | 生产包组装 | ✅ |
| `verify_release_tag.py` | 辅助 | tag 与 `project.version` 一致性校验 | ✅ |
| `verify_pypi_publish.py` | 辅助 | PyPI 发布后校验 | ✅ |
| `validate_pypi_wheels.py` | 辅助 | wheel 产物校验 | ✅ |
| `publish_pypi_rc1.py` | 辅助 | RC 发布脚本 | ✅ |
| `bootstrap_pypi_core_upload.sh` | 辅助 | core extra 首次上传引导 | ✅ |
| `tool_registry_config.py` | 辅助 | Tool registry 扫描配置 | ✅ |
| `tool_registry_engine.py` | 辅助 | Tool registry 扫描引擎 | ✅ |
| `tool_registry_models.py` | 辅助 | Tool registry 数据模型 | ✅ |
| `validate_tool_registry.py` | 辅助 | Tool registry CI 校验 | ✅ |
| `check_fractal_docs.py` | 辅助 | 分形 `_ARCH.md` 目录覆盖 + 可选 IOP 头门禁 | ✅ |
| `detect_blocking_io.py` | 辅助 | 阻塞 I/O 检测 | ✅ |

## 边界 enforcement 用法

```bash
python scripts/boundary_check.py              # CI 全量
python scripts/boundary_check.py --incremental  # pre-commit 增量
python scripts/boundary_check.py --fix          # 自动注释违规 import
python scripts/check_fractal_docs.py            # 分形 _ARCH 目录覆盖
```

性能基线见 `benchmarks/bench_boundary_detection.py`。

## 模块依赖

- **扫描目标**：`src/myrm_agent_harness/`
- **配置**：`boundary_config.py`（`ALLOWED_FRAMEWORK_PREFIXES`、`BANNED_PREFIXES`、`ALLOWED_PATHS`）
- **CI / pre-commit**：与 `tests/` 边界测试套件联动；`check_fractal_docs.py` 与 `tests/architecture/test_check_fractal_docs.py`
