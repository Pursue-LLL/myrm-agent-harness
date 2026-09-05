# Git Infrastructure Domain Architecture

## 1. 模块定位
`myrm_agent_harness.infra.git` 提供纯 Python 零子进程的 Git 元数据解析能力。
专为轻量沙箱、容器环境及高频分支监听设计，完全规避 `fork` 子进程带来的系统抖动与环境对 `git` 命令行二进制的强依赖。

## 2. 核心职责
- **零子进程文件流解析**：直接读取 `.git/HEAD`、`refs/` 及 `packed-refs`，解析耗时小于 0.05ms。
- **全生态 Git 结构兼容**：原生兼容标准 Git 仓库与 Linked Worktree（`.git` 为文件且通过 `gitdir:` 指向主仓库场景）。
- **分离头指针（Detached HEAD）安全格式化**：自动捕获裸 Commit Hash 并格式化为 `(detached:<sha[:7]>)`。
- **内存防抖缓存**：基于文件 `st_mtime` 维护线程安全的轻量级内存缓存，避免高频 I/O 穿透。
- **全量异常安全降级**：严密的只读文件异常白名单，任何权限或路径异常均静默返回空元数据，100% 不破坏上层调用方。

## 3. 对外接口
- `GitMetadata`：强类型不可变数据类，包含 `branch`、`commit`、`is_worktree`、`is_detached`。
- `resolve_git_metadata(workspace_dir: str | Path | None = None) -> GitMetadata`：完整解析接口。
- `resolve_git_branch(workspace_dir: str | Path | None = None) -> str | None`：轻量分支名提取便捷函数。

## 4. 文件清单
- `git_resolver.py`：纯 Python Git 元数据解析器与内存防抖缓存实现。

