# Four-Tier Persistent Memory and FTS5 Compaction Suite

## 架构定位与第一性原理
对标小米 MiMo Code / MiMo Desktop 专治长任务遗忘核心架构，通过解耦 Project、Session、Progress、Global 四重持久作用域与独立单文件 SQLite FTS5 引擎，实现零外部常驻依赖、毫秒级 BM25 全文检索召回与 `/dream` 自维护压缩循环。

## 模块拓扑与职责划分
1. **`models.py`**
   - 定义四重作用域枚举 `MemoryScope`（`GLOBAL`, `PROJECT`, `SESSION`, `PROGRESS`）。
   - 定义四重持久记录实体 `FourTierMemoryItem`。
   - 定义毫秒级全文召回结果 `FtsSearchResult`（含 BM25 排序分值与高亮片段）。
   - 定义梦境维护压缩审计报告 `DreamCompactionReport`。

2. **`fts_engine.py` (`SqliteFts5MemoryEngine`)**
   - 维护项目哈希单文件 SQLite 隔离库（`{project_hash}.db`），启用 WAL 模式与并发读写。
   - 管理 FTS5 虚拟表全文索引，支持原生的 BM25 排序评分；若底层环境不支持 FTS5 则优雅退化为 SQL LIKE 匹配，确保 100% 运行可靠性。
   - 提供增删改查与多作用域隔离过滤。

3. **`dream_compactor.py` (`FourTierDreamCompactor`)**
   - 实现 `/dream` 周期性（如 7 天）与按需触发的压缩提纯算法：自动扫描并合并同标题同作用域的零散碎片，剔除过期的临时进度条目，提炼项目长效知识资产。
