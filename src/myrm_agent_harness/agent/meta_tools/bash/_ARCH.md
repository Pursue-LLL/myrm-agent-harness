# bash/

## Overview
Bash tool module.

## Bash Python routing (SSOT)

| Need | Use | Do not use |
|------|-----|------------|
| Single tool call | Native LangChain tools (`file_read_tool`, …) | bash / `myrm_tools` |
| MCP batch script | `from skills.* import …` | `myrm_tools` |
| Cross-bash persistence | `/workspace` JSON files / `file_write_tool` | Paste JSON into chat / `myrm_tools` |
| Long-script progress | `MYRM_PROGRESS` echo (see `TOOL_DESCRIPTION`) | `myrm_tools.notify` |
| Orchestration spawn/notify | Dynamic Workflow → `myrm_tools.*` | Regular bash |

## Directory Layout

```
bash/
  __init__.py                    # 包门面（对外公共符号聚合出口）
  _ARCH.md                       # 本文件：域级入口文档
  bash_code_execute_tool.py      # 门面：bash 工具 LangChain 工厂
  bash_process_tools.py          # 门面：bash 后台进程管理工具工厂
  bash_auto_yield.py             # 门面：前台命令自动后台化工具
  bash_execution_error.py        # 共享：BashExecutionError 异常类型
  command_classifier.py          # 共享：命令分类器
  sensitive_parameter_redactor.py# 共享：敏感参数脱敏
  _executor/                     # 执行器域（聚合根 + mixins + 会话管理）
  _tool/                         # bash 工具能力域（描述/格式化/语义/多模态/监听）
  _compression/                  # 输出压缩域（语义压缩/eviction/声明式过滤）
  _security/                     # 安全域（执行前预检）
  _background/                   # 后台任务域（registry/ledger/spill/progress）
  scripts/                       # 沙箱 resilience 注入脚本
```

## File & Submodule Index

### 根：门面与共享

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | 包门面：聚合导出 8 个公共符号（`BashExecutor`、两个 tool 工厂、分类器、脱敏器）。 | — |
| `_tool_description.py` → `_tool/tool_description.py` | Internal | 静态缓存稳定 `TOOL_DESCRIPTION`。 | ✅ |
| `bash_code_execute_tool.py` | Core | `create_bash_code_execute_tool` LangChain 工厂；静态 TOOL_DESCRIPTION + OS hint；preflight ``ToolError`` 保留 ``guardrail_blocked``；``BashExecutionError`` 包装保留 stderr evicted ref。 | ✅ |
| `bash_process_tools.py` | Core | 统一 ``bash_process_tool``（actions list/output/kill/wait/write_stdin/submit_stdin/close_stdin）。 | ✅ |
| `bash_auto_yield.py` | Core | 前台白名单命令超时自动后台化。 | ✅ |
| `bash_execution_error.py` | Core | 结构化 BashExecutionError，携带 stdout/stderr eviction 引用。 | ✅ |
| `command_classifier.py` | Core | 命令分类器（READ/WRITE/DANGEROUS/NETWORK/GIT/SEARCH/PYTHON）。 | ✅ |
| `sensitive_parameter_redactor.py` | Core | 命令参数脱敏（--token/--password/--api-key 等）。 | ✅ |

### `_executor/` 执行器域

| File | Role | Description |
|------|------|-------------|
| `_executor/_ARCH.md` | Doc | 执行器域架构文档。 |
| `_executor/executor.py` | Core | BashExecutor 聚合根（DI 编排，MRO: Execute → Background → Prepare → Context）。 |
| `_executor/execute_mixin.py` | Core | 同步 execute() 编排；stdout/stderr 对称 eviction；失败路径双流落盘。 |
| `_executor/background_mixin.py` | Core | 后台进程 spawn + 裸尾 `&` 剥离。 |
| `_executor/prepare_mixin.py` | Core | MCP proxy、代码类型检测、技能 staging。 |
| `_executor/context_mixin.py` | Core | ExecutionContext 构建、OAuth issuer 作用域、事件日志。 |
| `_executor/constants.py` | Internal | 共享常量（MCP 超时下限）。 |
| `_executor/workspace_manager.py` | Core | 工作区薄委托（懒加载绑定存储根）。 |
| `_executor/skill_workspace_manager.py` | Core | 技能文件 staging 路径解析。 |
| `_executor/mcp_citation_handler.py` | Core | MCP Metadata Extractor。 |
| `_executor/session_spawn_lifecycle.py` | Core | 会话 spawn 生命周期标记。 |
| `_executor/event_logging.py` | Internal | 命令执行事件日志（脱敏+分类）。 |

### `_tool/` bash 工具能力域

| File | Role | Description |
|------|------|-------------|
| `_tool/_ARCH.md` | Doc | 工具能力域架构文档。 |
| `_tool/tool_description.py` | Internal | 静态缓存稳定 `TOOL_DESCRIPTION`。 |
| `_tool/formatting.py` | Core | 输出压缩/截断/脱敏/wrapping；`BASH_OUTPUT_MAX_CHARS` 单一事实源。 |
| `_tool/exit_semantics.py` | Core | Exit-code 语义解释。 |
| `_tool/helpers.py` | Core | BashInput schema、OS hint、上下文恢复。 |
| `_tool/multimodal.py` | Core | Vision ContentBlock 内联返回。 |
| `_tool/background_listeners.py` | Core | 后台 spawn ptc_notify 监听与退出分类。 |
| `_tool/output_filter_core.py` | Core | 增量输出轮询纯正则行过滤器。 |

### `_compression/` 输出压缩域

| File | Role | Description |
|------|------|-------------|
| `_compression/_ARCH.md` | Doc | 输出压缩域架构文档。 |
| `_compression/output_compressor.py` | Internal | 命令感知语义压缩入口（双引擎：硬编码 + YAML 声明式）；eviction preview 幂等跳过。 |
| `_compression/compressors.py` | Internal | 11 个具体命令压缩器（git/test/install/docker/build/compiler/log）。 |
| `_compression/output_eviction.py` | Internal | 大输出即时落盘 + 智能预览 + footer。 |
| `_compression/builtin_filters.yaml` | Config | 内置声明式过滤器（terraform/make/rsync/docker-pull）。 |

### `_security/` 安全域

| File | Role | Description |
|------|------|-------------|
| `_security/_ARCH.md` | Doc | 安全域架构文档。 |
| `_security/preflight_checks.py` | Internal | 执行前安全预检：URL 外泄、敏感路径、myrm_tools 守卫、交互检测、包注册表校验。 |

### `_background/` 后台任务域

见 [_background/_ARCH.md](_background/_ARCH.md)。

## Key Dependencies

- `backends`
- `runtime`
- `skills/mcp`
- `toolkits`
- `utils`
