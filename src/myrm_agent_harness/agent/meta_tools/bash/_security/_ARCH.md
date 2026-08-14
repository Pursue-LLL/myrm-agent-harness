# bash/_security/

## Overview
bash 执行前安全预检域。

## File Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | 域包入口。 | — |
| `preflight_checks.py` | Internal | 安全预检：URL 外泄、敏感路径、myrm_tools 守卫（AST/bash -c/-m/pipe stdin/引用 .py 扫描，raise ``ToolError`` + ``guardrail_blocked``）、交互命令检测、安装包注册表校验。 | ✅ |

## Key Dependencies

- `../bash_code_execute_tool`（预检接入点）
- `toolkits/code_execution/`（安全校验）
