# Revocable Provenance-Qualified Memory and Dream Diary Suite

## 架构定位与第一性原理
解决大模型长期记忆“无来源黑盒、不可撤销、删除后易死灰复燃、源历史易遭误删”的核心痛点，对标 OpenClaw 2.0 记忆所有权体系。

## 模块拓扑与职责划分
1. **`models.py`**
   - 定义不可变来源元数据 `ProvenanceMetadata`（会话 ID、消息 ID、Turn 序号、引用上下文切片、置信度与时间戳）。
   - 定义带来源限定的长期记忆模型 `ProvenanceQualifiedMemory`。
   - 定义定点撤销结果 `ForgetResult`（保证底层原始 Transcript 保持 100% 完整无损）。
   - 定义透明整合日记模型 `DreamDiaryEntry`。

2. **`provenance_store.py` (`ProvenanceMemoryStore`)**
   - 维护双向索引图谱：根据 memory_id 查询；根据 session_id 或 message_id 反向溯源查出贡献的所有长期记忆。

3. **`revocable_forget_engine.py` (`RevocableForgetEngine`)**
   - 原子级撤销派生记忆条目，登记墓碑指纹排除集（`TombstoneFingerprintSet`），彻底防止后续梦境整合时对同一段原始会话重复提取导致“死灰复燃”。

4. **`dream_diary_recorder.py` (`DreamDiaryRecorder`)**
   - 透明记录大模型后台梦境整合周期事件（扫描轮次、提升事实数、剪枝合并数、耗时与状态），消除暗箱操作疑虑。

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Package facade for revocable provenance. | ✅ |
| `dream_diary_recorder.py` | Core | Records and presents background dreaming memory consolidation cycles for transparent inspection. | ✅ |
| `models.py` | Types | Types and models for revocable provenance. | ✅ |
| `provenance_store.py` | Core | Stores and indexes long-term memories with bidirectional traceability to source transcripts. | ✅ |
| `revocable_forget_engine.py` | Core | Performs atomic point memory revocation and maintains tombstone exclusion fingerprints. | ✅ |
