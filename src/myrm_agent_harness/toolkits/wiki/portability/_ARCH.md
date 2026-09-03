# wiki/portability

## 架构概述

Deterministic full-vault ZIP export for `WikiStructure`. No Obsidian or HTTP dependencies.

## 文件清单

| 文件 | 地位 | 职责 | I/O/P |
|------|------|------|-------|
| `vault_archive.py` | 核心 | Walk `base_dir` (raw + wiki), exclude caches, emit manifest v2 ZIP | ✅ |
| `vault_git.py` | 核心 | Local `.git` init + auto-commit on vault mutations when `WikiConfig.enable_version_control` | ✅ |
| `obsidian_canvas.py` | 核心 | 纯文件格式工具：Obsidian .canvas JSON 文本节点提取、[[Wikilinks]] 正则解析与 1-Hop 依赖展开 | ✅ |
| `obsidian_tools.py` | 核心 | Agent 工具层：obsidian_vault_search、obsidian_vault_read 与 obsidian_inbox_write 审批回写 | ✅ |
| `__init__.py` | 入口 | Public exports (`build_vault_archive_zip`, `commit_vault_git_snapshot`, `create_obsidian_tools`, …) | ✅ |

Server `myrm-agent-server/app/services/wiki/obsidian/export.py` adds `.obsidian/graph.json` and README on top of this archive.
