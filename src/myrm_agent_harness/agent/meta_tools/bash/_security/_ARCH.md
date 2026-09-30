# bash/_security/

## Overview
bash 执行前安全预检域。

## File Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | 域包入口。 | — |
| `preflight_checks.py` | Internal | 安全预检：URL 外泄、工作区破坏性命令拦截（git reset --hard/clean -fd/restore ./rm -rf *，raise ``ToolError``）、myrm_tools 守卫（AST/bash -c/-m/pipe stdin/引用 .py 扫描，raise ``ToolError`` + ``guardrail_blocked``）、脱壳后台 '&' 运算符拦截、交互命令检测、安装包注册表校验。 | ✅ |
| `path_guard.py` | Internal | 路径保护预检：凭据路径经 `core.security.path::is_sensitive_file` 判定，读写皆拦；只读证据目录 `evidence/`·`user_inputs/` 与 Goal `protected_paths` 仅拦写，读操作放行，与 `EvidenceReadonlyValidator` 的 `VIEW` 放行同构；写意图按命令名（cp/rm/mv/tee/dd…）、脚本解释器（python/perl/node…）、输出旗标（-o/--output/--output-document）、重定向与就地编辑综合判定；复制/同步类命令（rsync/scp/sftp/smbclient）以末位操作数为目的地，方向确定为写，从而覆盖 `rsync -a dist/ evidence/` 这类目录目标；`tar` 按子命令区分方向（x/r/u 写，c/t 只读）；短旗标可捆绑（`xzf` 等），逐字母扫描，裸操作数（如 `out.tgz`）不参与扫描，`-O`/`--to-stdout` 输出到标准输出视为读；路径操作数同时检查裸词与 `--flag=`/`key=` 后的值，裸词不要求含分隔符，故 `rm -rf evidence` 与 `rm -rf evidence/report.pdf` 同等判定；内联 `sh -c`/`bash -c` 脚本按固定深度展开后重扫，带 scheme 的 URI 词跳过；commit message / `echo` 字面量清洗后放行；另保留一条正则兜底裸凭据文件名。 | ✅ |
| `shell_parse.py` | Internal | 两个守卫共用的 shell 解析原语：`SHELL_C_CMD_RE` 与 quote-aware 的 `extract_shell_c_payload`（识别 `bash -c '…'` 内联脚本）。集中于此，避免 myrm_tools 守卫与路径保护守卫在引号规则上各自演化。 | — |

## Key Dependencies

- `../bash_code_execute_tool`（预检接入点）
- `core/security/path`（敏感文件与只读证据规则 SSOT，与 `file_write_tool` 同源；经 `path_guard` 接入）
- `_security/shell_parse`（`extract_shell_c_payload`，本域内共用解析原语）
- `agent/middlewares/_session_context`（Goal `protected_paths` 上下文）
- `toolkits/code_execution/`（安全校验）
