# bash/_security/

## Overview
bash 执行前安全预检域。

## File Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | 域包入口。 | — |
| `preflight_checks.py` | Internal | 安全预检：URL 外泄、敏感路径与凭据（路径操作数经 `core.security.path_security::is_sensitive_file` 判定，与文件工具共用同一份规则；内联 `sh -c`/`bash -c` 脚本按固定深度展开后重扫，带 scheme 的 URI 词跳过；commit message / `echo` 字面量清洗后放行；另保留一条正则兜底裸凭据文件名）、工作区破坏性命令拦截（git reset --hard/clean -fd/restore ./rm -rf *，raise ``ToolError``）、myrm_tools 守卫（AST/bash -c/-m/pipe stdin/引用 .py 扫描，raise ``ToolError`` + ``guardrail_blocked``）、脱壳后台 '&' 运算符拦截、交互命令检测、安装包注册表校验。 | ✅ |

## Key Dependencies

- `../bash_code_execute_tool`（预检接入点）
- `core/security/path_security`（敏感文件规则 SSOT，与 `file_write_tool` 同源）
- `toolkits/code_execution/`（安全校验）
