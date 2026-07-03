# tests/architecture/ 模块架构

## 架构概述

CI 架构门禁：层边界、分形文档、PyPI wheel 打包不变量、tool registry 一致性。

## 文件清单

| 文件 | 地位 | 职责 | I/O/P |
| --- | --- | --- | --- |
| `test_toolkits_agent_boundary.py` | Gate | AST：`toolkits/` 禁止 import `myrm_agent_harness.agent` | — |
| `test_backends_agent_boundary.py` | Gate | AST：`backends/` 禁止 module-level import `myrm_agent_harness.agent` | — |
| `test_no_src_test_support.py` | Gate | `src/myrm_agent_harness/test_support/` 目录不得存在 | — |
| `test_toolkits_vendor_boundary.py` | Gate | `toolkits/` 禁止 top-level vendor 包名 / vendor 前缀模块名 | — |
| `test_artifact_vault_path_boundary.py` | Gate | harness `src/` 禁止 `.myrm/vault` 等品牌 vault 路径字面量 | — |
| `test_harness_boundary.py` | Gate | harness 禁止 import 业务层（server/control-plane） | — |
| `test_wheel_browser_assets.py` | Gate | wheel 须含 `browser/assets/ad_domains.txt`（≥3500 域） | — |
| `test_distribution_packaging.py` | Gate | 分发打包管线不变量（wheel build/install；`slow` 标记项在 CI `distribution-packaging-slow` job） | — |
| `test_distribution_wheel_artifact.py` | Gate | release/core wheel zip + `finalize_stripped_release_wheel` strip+verify | — |
| `distribution_wheel_helpers.py` | 辅助 | architecture 测试用最小合法 wheel zip 构造 | — |
| `test_distribution_manifest_gate.py` | Gate | 算法区新增模块须 manifest 或 `@distribution-public` | — |
| `test_distribution_codegen.py` | Gate | manifest codegen 新鲜度 + core IP import 可加载 | — |
| `test_public_api.py` | Gate | 公开 API 边界 smoke | — |
| `test_arch_no_placeholder.py` | Gate | `_ARCH.md` 禁止「见源码」等占位语 | — |
| `test_no_temp_docs_links.py` | Gate | tracked markdown 禁止链到 dev-shell `temp-docs/` | — |
| `test_no_star_imports.py` | Gate | 禁止 star import | — |
| `test_event_bus_naming_boundary.py` | Gate | 禁止 stale `EventBus` import（pubsub/broadcast rename 回归） | — |
| `test_manager_shared_barrel.py` | Gate | manager 共享 barrel 约束 | — |
| `test_tool_registry.py` | Gate | tool registry 与 `_TOOL_LAYERS` 一致 | — |
| `test_boundary_config.py` | Gate | boundary 配置完整性 | — |
| `test_boundary_autofix.py` | Gate | boundary `--fix` 行为 | — |
| `test_verify_release_tag.py` | Gate | release tag 与 `project.version` 对齐 | — |
| `test_verify_pypi_publish.py` | Gate | PyPI 发布后索引校验 | — |
| `test_validate_pypi_wheels.py` | Gate | wheel 产物数量/版本 + zip 内容 artifact 校验 | — |
| `test_check_fractal_docs.py` | Gate | 分形 `_ARCH.md` + strict IOP 头（`fractal_header_baseline.txt`）+ api/ 无 stub | — |
| `test_file_line_limit.py` | Gate | 单文件行数 baseline（>500 行须登记且不可增长） | — |
| `test_mixin_mro.py` | Gate | BrowserSession / ChatLiteLLM / OptimizationScheduler / SubagentExecutor / BashExecutor mixin MRO 顺序锁 | — |
| `test_executor_reexport.py` | Gate | `sub_agents/executor.py` `__all__` 聚合 re-export 完整性 | — |
| `test_bash_executor_reexport.py` | Gate | `meta_tools/bash/bash_executor.py` `__all__` 聚合 re-export 完整性 | — |
| `test_bash_code_execute_tool_reexport.py` | Gate | `meta_tools/bash/bash_code_execute_tool.py` `__all__` 聚合 re-export 完整性 | — |
| `test_no_ghost_registry_metadata.py` | Gate | `tool_registry.py` metadata maps 不得含无 @tool 源的幽灵键 | — |
| `test_types_reexport.py` | Gate | `backends/skills/types.py` `__all__` 聚合 re-export 完整性 | — |
| `test_validate_arch_inventory.py` | Gate | `_ARCH.md` 文件表 vs 同级 `.py` 一致性（table-only 解析）；含 agent/ 与全 harness subprocess gate | — |
| `test_readme_claims.py` | Gate | README 声明与实际代码/性能基准一致性校验 | — |
| `test_core_dependencies.py` | Gate | core vs optional/dev 分层：4 项 optional-only 包不得回 core；uv.lock core 与 pyproject 对齐 | — |

## 运行

```bash
pytest tests/architecture/ -m "architecture and not slow"
pytest tests/architecture/test_distribution_packaging.py -m "architecture and slow"
uv run python scripts/check_fractal_docs.py
uv run python scripts/validate_arch_inventory.py --root src/myrm_agent_harness
uv run python scripts/check_file_line_limit.py
```
