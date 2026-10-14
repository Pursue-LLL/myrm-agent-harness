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
| `sync_distribution_metadata.py` | 核心 | 从 `core_manifest.yaml` 再生成 `runtime/install_guard` codegen 产物与 compiled-core pin | ✅ |
| `check_package_root_layout.py` | Gate | 包根禁止平铺实现模块（仅允许 `__init__.py` / `client.py`）；`tests/` 根禁止散落测试模块（仅允许 `__init__.py` / `conftest.py`）；回归 legacy 平铺文件名 | — |
| `assemble_production.py` | 辅助 | 生产包组装 | ✅ |
| `verify_release_tag.py` | 辅助 | tag 与 `project.version` 一致性校验 | ✅ |
| `verify_pypi_publish.py` | 辅助 | PyPI 发布后索引校验（6 core 必选；musl 已索引则必选） | ✅ |
| `validate_pypi_wheels.py` | 辅助 | wheel 数量/版本 + zip artifact 校验 | ✅ |
| `publish_pypi_rc1.py` | 辅助 | RC 发布脚本 | ✅ |
| `bootstrap_pypi_core_upload.sh` | 辅助 | core extra 首次上传引导 | ✅ |
| `tool_registry_config.py` | 辅助 | Tool registry 扫描配置 | ✅ |
| `tool_registry_engine.py` | 辅助 | Tool registry 扫描引擎 | ✅ |
| `tool_registry_models.py` | 辅助 | Tool registry 数据模型 | ✅ |
| `validate_tool_registry.py` | 辅助 | Tool registry CI 校验（注册一致性 + 治理覆盖门禁：遍历注册内置全集 / 权限类型矩阵 / EXPLICIT_MCP_FALLBACK 第三态 / DYNAMICALLY_RESOLVED_TOOL_NAMES SSOT 消费 / BUILTIN↔注册双向一致性 / RULESET_COVERAGE_WHITELIST 双向一致性（stale+orphan）/ EXTERNAL server-managed 标注 / safety / canonical 参数 / forbidden legacy terms（bindmode、catalog_invoke、delegate_to_agent_tool、profile seed 内 delegate_agent 权限键）；`--json` 输出覆盖矩阵，矩阵含 `whitelist_orphan` 标注使 orphan 声明对审计报表可见） | ✅ |
| `validate_arch_inventory.py` | 辅助 | `_ARCH.md` 文件清单表格 vs 同级 `.py` 一致性校验（仅解析表格行）+ `--md-refs` 全仓 markdown 路径引用真实性校验（反引号 span 与内联链接 `[label](path)` 统一管道；显式相对路径 / 跨仓 alias / harness 模块快捷三态解析，渐退剥离 symbol 后缀；`--root` 仓根或 server 仓等跨仓扫描仅跑 md-refs，不跑表格） | ✅ |
| `md_ref_validator.py` | 辅助 | md 引用校验核心：`scan_md_refs` / `_extract_md_refs` / `_resolve_md_ref` / 反引号 span 与内联链接统一解析（内联链接额外校验带扩展名的裸文件名如 `[x](other.md)`，反引号保留 `/` 门槛以免误判 prose）/ 渐退 symbol 剥离（拒绝截断到 `../..` 等父级标记）/ 源码根自动发现（harness `src/myrm_agent_harness`，server `app/`，跨仓快捷引用按被扫描仓识别）/ 无扩展名引用探测 TS·JS 源扩展名 / 导入规格表按首列源文件目录锚定 / `{placeholder}` 符号行跳过 / 非 UTF-8 文档跳过 / 白名单（`SKILL_SYSTEM.md` 竞品规划表、`eval/_ARCH.md` 候选决策表、`prebuilt_skills/` 运行时产物），被 `validate_arch_inventory.py` 复用 | ✅ |
| `check_fractal_docs.py` | 辅助 | 分形 `_ARCH.md` 目录覆盖 + IOP 头 baseline 门禁（`fractal_header_baseline.txt`） | ✅ |
| `check_file_line_limit.py` | 辅助 | 单文件行数 baseline 门禁（>500 行须登记且不可增长）；`--incremental` 仅扫描 git 变更文件（pre-commit），无 git 时回退全量 | ✅ |
| `check_test_source_assertions.py` | 辅助 | 测试源码文本断言门禁：以 `ast` 识别「读 `.py` 源码 + 断言字符串包含」写法，强制改用语法树断言，使断言不受格式化换行影响；`--incremental` 供 pre-commit 使用 | ✅ |
| `check_module_coverage.py` | 辅助 | 每模块覆盖率下限门禁：读取 `.coverage` 数据，对 `COVERAGE_FLOORS` 登记的模块逐个校验执行率，不嵌套执行 pytest | ✅ |
| `check_module_reachability.py` | Gate | 模块可达性门禁 CLI：harness 包除公开面 `api/` 外每个顶层目录的直接子项（单元）必须有生产消费者（本包或 server 树的存活代码）；`--server` 以同一引擎审计 server 树自身单元（`--server-root` 指定 `app/` 目录，`channels/`、`startup/` 因按名称加载/由树外 `run.py` 导入而作为根）；无白名单、无 baseline；server 树缺失时显式输出 `NOT EVALUATED`（`--require-server` / `--server` 则失败）；`--incremental` 仅在 harness 源码变更时运行（供 git hook 调用，`.pre-commit-config.yaml` 未登记，不会自动触发） | ✅ |
| `module_reachability_engine.py` | Gate | 可达性静态引擎：单元分类、hub 再导出解析（含 lazy 表与子树 exporter 回退）与可达闭包；`root_dirs`（默认 `api/`）、包根模块、`__main__.py`、带 `if __name__ == "__main__"` 块的模块（`python -m` 可执行入口，如 skill 以命令行调用的 `code_graph/cli.py`）、`[project.scripts]` 为根；server 树作为 `Consumer` 以同一引擎分析，仅其根与由根可达的单元计为消费者，死 server 单元不会让 harness 单元存活 | ✅ |
| `module_reachability_facts.py` | Gate | 可达性逐文件证据抽取：以全限定点路径引用建模（导入路径、导入后加载的名字、模块属性链、点路径字符串、`module:attr`）；hub 内 `from .x import Y` 再导出/别名不算使用，hub 内裸 `import a.b.c`（副作用注册）算消费者；`api/` 与包根 `__init__.py` 为公开面 | ✅ |
| `check_import_resolvability.py` | Gate | 导入可解析性门禁 CLI：每条一方 import（含函数内、`try/except` 内、`TYPE_CHECKING` 内）必须指向真实存在的模块，`from M import N` 的 `N` 必须是子模块或 `M` 导入时绑定的名字；无白名单、无 baseline；`--package NAME=DIR` 与 `--scan NAME` 可把 server `app/` 树对照 harness 源码检查；`--incremental` 仅在 harness `.py` 变更时运行（pre-commit）；解析失败的文件与空扫描显式报错而非放行 | ✅ |
| `import_resolvability_engine.py` | Gate | 导入可解析性静态引擎：一次索引各根包全部模块的导入期符号（定义、赋值、`for`/`with` 目标、import 绑定、`__all__`、`import *` 再导出）；带模块级 `__getattr__` / `globals()` 改写的动态命名空间与无法解析的文件一律放行其名字，只报能证伪的导入；跨根解析、仅对 `scan` 根报告 | ✅ |
| `file_line_baseline.txt` | 辅助 | legacy 大文件 grandfather 清单：允许 >500 行但不得超过登记行数；拆分至 ≤500 后移除 | — |
| `fractal_header_baseline.txt` | 辅助 | 允许暂缺 IOP 头的 legacy 路径清单（相对 `src/`）；新文件不得加入 | — |
| `detect_blocking_io.py` | 辅助 | 阻塞 I/O 检测 | ✅ |
| `measure_turn1_token_inventory.py` | 辅助 | Turn-1 bind_tools token 成本测量（tiktoken planning SSOT） | ✅ |
| `measure_tool_schema_tokens.py` | 辅助 | Tool Description + JSON Schema Parameters 细粒度 token 成本测量与导出 | ✅ |
| `update_component_snapshots.py` | 辅助 | 更新 `tests/architecture/test_component_snapshot_bounded_diff.py` 所用的核心组件快照基线 | ✅ |

## 边界 enforcement 用法

```bash
python scripts/boundary_check.py              # CI 全量
python scripts/boundary_check.py --incremental  # pre-commit 增量
python scripts/boundary_check.py --fix          # 自动注释违规 import
python scripts/check_fractal_docs.py            # 目录 _ARCH 覆盖
python scripts/check_fractal_docs.py --strict-headers --header-baseline scripts/fractal_header_baseline.txt --no-stub
python scripts/check_file_line_limit.py --baseline scripts/file_line_baseline.txt
python scripts/check_file_line_limit.py --incremental  # pre-commit: changed files only
python scripts/validate_arch_inventory.py --root src/myrm_agent_harness
python scripts/validate_arch_inventory.py --root . --md-refs          # 仓根（含顶层文档）引用校验
python scripts/validate_arch_inventory.py --root ../myrm-agent/myrm-agent-server --md-refs  # 跨仓扫描
python scripts/check_test_source_assertions.py            # 全量扫描 tests/
python scripts/check_test_source_assertions.py --incremental  # pre-commit: changed tests only
python scripts/check_module_coverage.py --data .coverage  # 需先以 --cov 产出覆盖率数据
python scripts/check_module_reachability.py               # 全量：harness 每个单元须有生产消费者
python scripts/check_module_reachability.py --server      # server 树自身单元（server CI 调用，--server-root 指定 app/）
python scripts/check_module_reachability.py --incremental  # 仅 harness 源码变更时运行（hook 用，当前未登记）
python scripts/check_module_reachability.py --json        # 机器可读（死单元 / 仅 server 消费单元）
python scripts/check_import_resolvability.py              # 全量：每条一方 import 须指向真实模块与名字（CI）
python scripts/check_import_resolvability.py --incremental  # pre-commit：仅 harness 源码变更时运行
python scripts/check_import_resolvability.py \
    --package myrm_agent_harness=src/myrm_agent_harness \
    --package app=../myrm-agent/myrm-agent-server/app --scan app   # server 树对照 harness（server CI 调用）
```

Pre-commit runs `validate_arch_inventory.py` via hook `harness-arch-inventory-check` and `check_file_line_limit.py` via hook `harness-line-limit-check`, `check_test_source_assertions.py` via hook `harness-test-source-assertion-check`, and `check_import_resolvability.py` via hook `harness-import-resolvability-check` (see `.pre-commit-config.yaml`). CI runs the import gate in `.github/workflows/boundary-check.yml`; the server repo runs it against its own `app/` tree from `scripts/ci/run_architecture_gates.sh` whenever the harness source sits beside it.

## File line grandfather 策略

`check_file_line_limit.py` 与 `file_line_baseline.txt` 配合实现**渐进式行数治理**：

| 文件类型 | 规则 |
|----------|------|
| 未登记的新 `.py` | 不得超过 500 行 |
| baseline 登记的 legacy `.py` | 不得超过 baseline 中的行数上限（禁止变胖） |
| 拆分后 ≤500 行 | 从 baseline 移除条目 |

登记格式：`myrm_agent_harness/.../module.py<TAB>当前行数`（路径相对 `src/`）。CI 见 `tests/architecture/test_file_line_limit.py`。

性能基线见 `benchmarks/bench_boundary_detection.py`。

## 模块依赖

- **扫描目标**：`src/myrm_agent_harness/`
- **配置**：`boundary_config.py`（`ALLOWED_FRAMEWORK_PREFIXES`、`BANNED_PREFIXES`、`ALLOWED_PATHS`）
- **CI / pre-commit**：与 `tests/` 边界测试套件联动；`check_fractal_docs.py` 与 `tests/architecture/test_check_fractal_docs.py`
