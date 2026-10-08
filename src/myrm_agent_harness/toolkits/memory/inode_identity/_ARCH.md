# Mempalace Inode Identity 架构契约 (_ARCH.md)

## 1. 模块定位
本模块是长期记忆系统中针对代码库与工作区目录同步（Sync）的核心身份裁决引擎，直接对标 `mempalace #2563`。

## 2. 第一性原理与核心目标
传统目录同步仅依赖路径字符串匹配，在 bind-mount、换卷、符号链接以及目录重命名/移动场景下极易发生：
1. **重复同步灾难（Double Sync）**：路径变更时被误判为全新目录，导致全量重新提取与向量库膨胀；
2. **幽灵删除风险**：旧路径被误判为物理删除，触发级联软删除导致历史长期记忆丢失；
3. **跨卷碰撞（Cross-Volume Collision）**：在单用 `st_ino` 时发生跨设备 inode 数字碰撞。

本模块构建物理二元组 `(device_id, inode_id)` + 根指纹三维身份裁决体系，实现：
- 零依赖路径文本的底层物理设备与 Inode 精准锁定；
- 目录重命名/移动（Move Detection）毫秒级原子重定向，保护既有索引与记忆指针；
- 重建/换卷冲突防御（Rebuild Warning）；
- 单机、桌面端（Tauri）与云托管沙箱（Docker Persistent Volume）三部署模式 100% 同构兼容。

## 3. 分形架构规范
- `models.py`: 严格强类型领域模型与枚举，杜绝任何 `typing.Any`；
- `resolver.py`: 跨平台设备与 Inode 解析器，安全处理软链接与根目录特征哈希；
- `guard.py`: 目录身份注册表比对与同步守卫决策引擎；
- `facade.py`: 对外统一无状态门面与单例注入。

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Inode Identity Subsystem exports and interfaces. | ✅ |
| `facade.py` | Facade | Unified stateless facade and singleton injection for Inode Identity. | ✅ |
| `guard.py` | Guard | Directory identity registry comparator and sync guard decision engine. | ✅ |
| `models.py` | Models | Strongly-typed domain models and invariants for Inode Identity. | ✅ |
| `resolver.py` | Resolver | Cross-platform device and Inode resolver with root feature hashing. | ✅ |
