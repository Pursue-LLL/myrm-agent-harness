# bash/_tool/

## Overview
bash 工具横切能力域：LLM 描述提示词、输出格式化/截断、退出码语义、多模态、后台监听、增量输出过滤。

## File Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | 域聚合出口：导出 `TOOL_DESCRIPTION`。 | — |
| `tool_description.py` | Internal | 静态缓存稳定 `TOOL_DESCRIPTION`（能力/合并规则/后台任务/eviction 读取提示）。 | ✅ |
| `formatting.py` | Core | 输出压缩编排、截断、脱敏、wrapping；消费压缩域 `BASH_OUTPUT_MAX_CHARS` 做硬截断。 | ✅ |
| `exit_semantics.py` | Core | Exit-code 语义解释（grep=1、git diff、信号）。 | ✅ |
| `helpers.py` | Core | BashInput schema（reason 必填）、OS hint、上下文恢复/访问追踪。 | ✅ |
| `multimodal.py` | Core | Vision ContentBlock 内联返回（生成图片）。 | ✅ |
| `background_listeners.py` | Core | 后台 spawn ptc_notify 监听与退出分类。 | ✅ |
| `output_filter_core.py` | Core | 增量输出轮询纯正则行过滤器（pattern ≤256 字符）。 | ✅ |

## Key Dependencies

- `../_compression/output_compressor`（语义压缩，单向依赖）
- `../_compression/constants`（`BASH_OUTPUT_MAX_CHARS` 阈值消费方，单向依赖）
- `../_background`（后台监听）
- `../_executor/error`（共享异常）
