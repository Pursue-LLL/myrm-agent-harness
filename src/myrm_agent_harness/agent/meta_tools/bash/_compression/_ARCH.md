# bash/_compression/

## Overview
bash 输出压缩域：命令感知语义压缩（双引擎）、大输出即时 eviction 落盘、声明式 YAML 过滤器。

## File Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | 域聚合出口：导出 `compress_output`、`maybe_evict_large_output`、`BASH_OUTPUT_MAX_CHARS`。 | — |
| `constants.py` | Internal | 压缩域常量：`BASH_OUTPUT_MAX_CHARS`（字符截断阈值单一事实源）。 | ✅ |
| `output_compressor.py` | Internal | 语义压缩入口：硬编码 14 条压缩器匹配规则 + DeclarativeFilterEngine；eviction banner 幂等跳过。 | ✅ |
| `compressors.py` | Internal | 11 个具体压缩器（git diff/log/operation、ls、test、package install、docker build、build tool、compiler error、log dedup）。 | ✅ |
| `output_eviction.py` | Internal | 大输出（token>20k 或 chars>8k）即时落盘 `.context/{chat_id}/evicted/` + 智能预览 + file_read_tool footer。 | ✅ |
| `builtin_filters.yaml` | Config | 内置声明式过滤器（terraform-plan/make/rsync/docker-pull）。 | — |

## Key Dependencies

- `.constants`（`BASH_OUTPUT_MAX_CHARS` 字符截断阈值单一事实源）
- `agent.context_management.strategies.filter`（token 阈值）
- `agent.context_management.infra.evicted_content`（落盘 + footer）
