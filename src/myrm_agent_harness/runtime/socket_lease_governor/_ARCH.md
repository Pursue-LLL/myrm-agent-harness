# socket_lease_governor/

## Overview
全链路连接池枯竭防御、文件描述符硬配额保护与 Socket 租约中枢套件.

## File Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | 全链路连接池枯竭防御、文件描述符硬配额保护与 Socket 租约中枢套件. | — |
| `fd_watermark_sentinel.py` | Core | 操作系统文件描述符（FD）水位监控与紧急反压哨兵模块. | ✅ |
| `nofile_limit_lifter.py` | Core | 进程级文件描述符软限制（RLIMIT_NOFILE）自适应抬升模块. | ✅ |
| `socket_governor_types.py` | Core | 连接池枯竭防御与 Socket 租约中枢类型定义模块. | ✅ |
| `socket_lease_governor.py` | Core | 全系统连接池枯竭防御与统一 Socket 租约中枢模块. | ✅ |
