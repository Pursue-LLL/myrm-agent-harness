# scripts/ 模块架构

## 架构概述

Harness 仓维护脚本：框架-业务边界 enforcement、PyPI 发布校验、compiled-core 构建与 tool registry 校验。详见 [ARCHITECTURE.md](../ARCHITECTURE.md)。

## 文件清单

| 文件 | 地位 | 职责 | I/O/P |
| --- | --- | --- | --- |
| `boundary_check.py` | 核心 | CLI：全量/增量扫描 `src/myrm_agent_harness/` 非法跨层 import | ✅ |
| `boundary_config.py` | 核心 | 白名单前缀、禁止前缀、允许路径配置 | ✅ |
| `boundary_engine.py` | 核心 | AST 静态/动态 import 检测引擎 | ✅ |
| `build_core.py` | 核心 | compiled-core 构建 + wheel 后 inline artifact verify | ✅ |
| `build_release_wheel.py` | 核心 | 发布 wheel 组装 + strip 后 inline artifact verify | ✅ |
| `sync_distribution_metadata.py` | 核心 | 从 `core_manifest.yaml` 再生成 `_core_ip_manifest.py` 与 compiled-core pin | ✅ |
| `assemble_production.py` | 辅助 | 生产包组装 | ✅ |
| `verify_release_tag.py` | 辅助 | tag 与 `project.version` 一致性校验 | ✅ |
| `verify_pypi_publish.py` | 辅助 | PyPI 发布后索引校验（6 core 必选；musl 已索引则必选） | ✅ |
| `validate_pypi_wheels.py` | 辅助 | wheel 数量/版本 + zip artifact 校验 | ✅ |
| `publish_pypi_rc1.py` | 辅助 | RC 发布脚本 | ✅ |
| `bootstrap_pypi_core_upload.sh` | 辅助 | core extra 首次上传引导 | ✅ |
| `tool_registry_config.py` | 辅助 | Tool registry 扫描配置 | ✅ |
| `tool_registry_engine.py` | 辅助 | Tool registry 扫描引擎 | ✅ |
| `tool_registry_models.py` | 辅助 | Tool registry 数据模型 | ✅ |
| `validate_tool_registry.py` | 辅助 | Tool registry CI 校验 | ✅ |
| `validate_arch_inventory.py` | 辅助 | `_ARCH.md` 文件清单表格 vs 同级 `.py` 一致性校验（仅解析表格行） | ✅ |
| `check_fractal_docs.py` | 辅助 | 分形 `_ARCH.md` 目录覆盖 + IOP 头 baseline 门禁（`fractal_header_baseline.txt`） | ✅ |
| `check_file_line_limit.py` | 辅助 | 单文件行数 baseline 门禁（>500 行须登记且不可增长） | ✅ |
| `file_line_baseline.txt` | 辅助 | 允许超过 500 行的 legacy 路径清单（相对 `src/`，含当前行数上限） | — |
| `fractal_header_baseline.txt` | 辅助 | 允许暂缺 IOP 头的 legacy 路径清单（相对 `src/`）；新文件不得加入 | — |
| `detect_blocking_io.py` | 辅助 | 阻塞 I/O 检测 | ✅ |

## 边界 enforcement 用法

```bash
python scripts/boundary_check.py              # CI 全量
python scripts/boundary_check.py --incremental  # pre-commit 增量
python scripts/boundary_check.py --fix          # 自动注释违规 import
python scripts/check_fractal_docs.py            # 目录 _ARCH 覆盖
python scripts/check_fractal_docs.py --strict-headers --header-baseline scripts/fractal_header_baseline.txt --no-stub
python scripts/check_file_line_limit.py --baseline scripts/file_line_baseline.txt
python scripts/validate_arch_inventory.py --root src/myrm_agent_harness
```

Pre-commit runs `validate_arch_inventory.py` via hook `harness-arch-inventory-check` (see `.pre-commit-config.yaml`).

性能基线见 `benchmarks/bench_boundary_detection.py`。

## 模块依赖

- **扫描目标**：`src/myrm_agent_harness/`
- **配置**：`boundary_config.py`（`ALLOWED_FRAMEWORK_PREFIXES`、`BANNED_PREFIXES`、`ALLOWED_PATHS`）
- **CI / pre-commit**：与 `tests/` 边界测试套件联动；`check_fractal_docs.py` 与 `tests/architecture/test_check_fractal_docs.py`
