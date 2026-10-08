# Document Attachment Lifecycle & Ownership Architecture Contract

## 1. 架构动机与第一性原理 (Motivation & First Principles)

在 Agent 长期运行的单机沙箱环境中，Agent 执行代码或分析任务时会持续生成多模态附件（图表、数据快照、导出文件等）。
传统的附件管理常采用**跨文档全局去重模型**（Global Deduplication Table），仅以 `(attachment_hash)` 作为主键维护物理对象，并通过外键或中间多对多表关联到 Document。

这种设计在垃圾回收（GC Reclaim Sweep）时存在严重的物理确定性缺陷：
1. **GC Bailed Out 物理泄露**：当某个文档被删除时，GC 扫描器无法在分布式/多分枝单机环境下确定全局是否仍有隐藏引用，为了安全只能放弃物理删除；当最终引用该文件的最后一个文档也被删除时，该 Blob 变成了彻底失联的“孤儿幽灵文件”，造成磁盘永久性泄漏。
2. **所有权模糊**：文档级权限、生命周期和清理无法做到原子化与本地判定。

## 2. 核心架构裁决 (Core Architectural Decisions)

本套件严格遵循 `AttachmentBelongsToDocument` 的架构裁决：
1. **以微小元数据冗余换取回收确定性 (Ownership-First Architecture)**：
   - 彻底放弃全局去重中间表，确立文档强属主模型：每个附件记录强绑定到特定的 `document_id`。
   - 复合唯一约束或属主行：`(document_id, attachment_id)`。
   - 相同物理哈希被两个文档引用时，各自持有一行元数据记录。元数据仅占几十字节，换取生命周期判定 100% 降维为文档本地判定。
2. **延迟物理清空与引用计数追踪 (Deferred Physical Blob Reclaim)**：
   - 底层物理 Blob 共享 `storage_key`（基于哈希），物理文件绝不重复拷贝。
   - 维护单调可靠的 `ref_count`：每当文档挂载附件时递增，文档解除挂载或删除文档时递减。
   - 垃圾回收器 `DeterministicReclaimSweeper` 在引用计数降为 0 时，确定性执行物理文件 unlink，彻底消除幽灵泄露。
3. **存量孤儿清洗与平滑平铺迁移 (Orphan Cleansing Migration)**：
   - 迁移引擎将存量多对多关联平铺拆解为文档专属记录。
   - 历史遗留的无主悬挂记录在迁移阶段原子 Drop 清洗，根除历史技术债。

## 3. 分层与调用边界 (Layer Boundaries)

- **Harness 框架层 (`myrm_agent_harness.toolkits.memory.document_attachment`)**：
  提供纯单机高吞吐的属主引擎、引用计数器、物理 Sweeper 与平铺迁移器，暴露统一门面 `DocumentAttachmentSuite`。框架层无多租户，无外部网络依赖。
- **Server 业务层 (`myrm_agent_server.services.memory.document_attachment`)**：
  提供 REST API 路由与业务依赖注入，严格通过 Harness 顶层门面交互，严守 0 deep import。

## 4. 文件清单 (File Index)

| 文件 | 角色 | 职责 | I/O/P |
|------|------|------|-------|
| `__init__.py` | 门面 | 导出附件模型、属主引擎、回收扫描器与统一套件 | ✅ |
| `models.py` | 类型 | 附件元数据、属主绑定、清理候选与统计模型 | ✅ |
| `ownership_engine.py` | 核心 | 文档属主绑定引擎、引用计数追踪与元数据管理 | ✅ |
| `reclaim_sweep.py` | 核心 | 确定性零引用物理文件垃圾回收与防泄漏清理扫描器 | ✅ |
| `migration_engine.py` | 核心 | 历史多对多附件向属主模型平铺迁移与孤儿数据清理器 | ✅ |
| `facade.py` | 门面 | 文档附件生命周期与所有权治理统一套件门面 | ✅ |
