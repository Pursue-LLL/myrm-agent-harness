# tests/architecture/ 模块架构

## 架构概述

CI 架构门禁：层边界、分形文档、PyPI wheel 打包不变量、tool registry 一致性。

## 文件清单

| 文件 | 地位 | 职责 | I/O/P |
| --- | --- | --- | --- |
| `test_toolkits_agent_boundary.py` | Gate | AST：`toolkits/` 禁止 import `myrm_agent_harness.agent` | — |
| `test_harness_boundary.py` | Gate | harness 禁止 import 业务层（server/control-plane） | — |
| `test_wheel_browser_assets.py` | Gate | wheel 须含 `browser/assets/ad_domains.txt`（≥3500 域） | — |
| `test_distribution_packaging.py` | Gate | 分发打包管线不变量 | — |
| `test_public_api.py` | Gate | 公开 API 边界 smoke | — |
| `test_arch_no_placeholder.py` | Gate | `_ARCH.md` 禁止「见源码」等占位语 | — |
| `test_no_temp_docs_links.py` | Gate | tracked markdown 禁止链到 dev-shell `temp-docs/` | — |
| `test_no_star_imports.py` | Gate | 禁止 star import | — |
| `test_manager_shared_barrel.py` | Gate | manager 共享 barrel 约束 | — |
| `test_tool_registry.py` | Gate | tool registry 与 `_TOOL_LAYERS` 一致 | — |
| `test_boundary_config.py` | Gate | boundary 配置完整性 | — |
| `test_boundary_autofix.py` | Gate | boundary `--fix` 行为 | — |
| `test_verify_release_tag.py` | Gate | release tag 与 `project.version` 对齐 | — |
| `test_verify_pypi_publish.py` | Gate | PyPI 发布后索引校验 | — |
| `test_validate_pypi_wheels.py` | Gate | wheel 产物校验 | — |
| `test_check_fractal_docs.py` | Gate | `scripts/check_fractal_docs.py` 目录 `_ARCH.md` 覆盖 | — |

## 运行

```bash
pytest tests/architecture/ -m architecture
uv run python scripts/check_fractal_docs.py
```
