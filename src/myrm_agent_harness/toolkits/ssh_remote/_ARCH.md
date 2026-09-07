# ssh_remote 模块架构

---

## 架构概述

提供安全受控的远程主机 SSH 执行与 SFTP 传输工具包。具备高危破坏性命令拦截、超时守卫、以及基于 `TerminalLogDistiller` 的长日志高信噪比蒸馏，防范大模型上下文污染。

---

## 文件清单

| 文件 | 地位 | 职责 | I/O/P |
| --- | --- | --- | --- |
| `__init__.py` | 包入口 | 导出模型与执行器类 | ✅ |
| `models.py` | 核心模型 | 定义主机规格 `SSHHostSpec`、执行结果 `SSHCommandResult` 与传输结果 `SFTPTransferResult` | ✅ |
| `executor.py` | 核心执行器 | 异步 SSH/SFTP 执行、安全正则拦截与日志蒸馏 | ✅ |
