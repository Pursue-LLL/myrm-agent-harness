# 存储系统设计文档

> 最后更新：2026-03-26 | 对应代码版本：当前 `toolkits/storage/` 目录

---

## 1. 设计目标

- **统一接口**：所有存储操作通过 `StorageProvider` ABC 进行，业务层无需关心底层实现
- **协议驱动**：框架层定义协议，业务层注入实现（依赖反转）
- **路径约定**：通过 `paths.py` 统一管理存储路径，确保全局一致性
- **零业务耦合**：存储层只关注数据存取，不包含任何业务逻辑

---

## 2. 架构分层

```
┌─────────────────────────────────────────────────────────┐
│ 业务层 (app/)                                            │
│                                                          │
│  app/platform_utils/__init__.py                          │
│    └─ get_storage_provider()                             │
│       ├─ local 模式 → create_storage_provider()          │
│       │                → LocalStorageBackend              │
│       └─ sandbox 模式  → S3StorageBackend (业务层实现)       │
│                                                          │
│  app/core/storage/smart_cache.py                         │
│    └─ SmartCachedStorage (本地缓存 + 远程存储透明同步)     │
│                                                          │
│  app/core/storage/service.py                             │
│    └─ FileStorageService (文件上传/下载/管理)             │
│                                                          │
│  app/core/skills/store/service.py                        │
│    └─ SkillStoreService (技能存储管理)                    │
└──────────────────────────┬──────────────────────────────┘
                           │ 依赖方向 ↓
┌──────────────────────────┴──────────────────────────────┐
│ 框架层 (myrm_agent_harness/toolkits/storage/)             │
│                                                          │
│  base.py          → StorageProvider (ABC), FileInfo              │
│  _fs_backend.py   → BaseFileSystemBackend (aiofiles + errno)     │
│  local.py         → LocalStorageBackend (继承 BaseFileSystemBackend) │
│  persistent.py    → PersistentStorageBackend (继承 BaseFileSystemBackend) │
│  factory.py       → create/get/set_storage_provider              │
│  config.py        → StorageConfig, StorageMode                   │
│  types.py         → FilePurpose, SkillType                       │
│  paths.py         → 路径生成/解析工具 (20+ 函数)                 │
│                                                              │
│ 兼容层 (myrm_agent_harness/backends/storage/)              │
│  local.py       → 重导出 toolkits/storage/local 的实现       │
└──────────────────────────────────────────────────────────────┘
```

---

## 3. 核心协议

### 3.1 StorageProvider (ABC)

唯一的存储协议，定义 11 个方法：

| 方法 | 签名 | 说明 |
|------|------|------|
| `read` | `(key: str) -> bytes` | 读取文件内容 |
| `read_text` | `(key: str, encoding) -> str` | 读取文本文件 |
| `write` | `(key: str, content: bytes, content_type?) -> None` | 写入文件 |
| `write_text` | `(key: str, content: str, encoding?, content_type?) -> None` | 写入文本文件 |
| `delete` | `(key: str) -> None` | 删除文件/目录 |
| `exists` | `(key: str) -> bool` | 检查文件是否存在 |
| `list` | `(prefix?, recursive?) -> list[str]` | 列出文件 |
| `info` | `(key: str) -> FileInfo` | 获取文件元信息 |
| `copy` | `(src_key, dst_key) -> None` | 复制文件/目录 |
| `move` | `(src_key, dst_key) -> None` | 移动文件 |
| `get_url` | `(key: str, expires_in?) -> str` | 获取文件访问 URL |

### 3.2 命名空间隔离

`StorageProvider` 内置 namespace 支持，自动为所有路径添加前缀：

```python
storage = LocalStorageBackend("./storage", namespace="sandboxes/user_alice")
await storage.write("file.txt", b"content")
# 实际路径: ./storage/sandboxes/user_alice/file.txt
```

内部通过 `_get_full_key()` / `_strip_namespace()` 透明处理。

---

## 4. 实现

### 4.0 BaseFileSystemBackend (框架层基类)

- **位置**: `toolkits/storage/_fs_backend.py`
- **用途**: 文件系统后端的公共基类，提供 aiofiles I/O 和 errno 错误处理的统一实现
- **异步策略**: `aiofiles` 真异步 I/O（read/write/delete/exists/info/copy/move/get_url）
- **错误处理**: 统一的 `errno` 翻译（ENOSPC / ENAMETOOLONG / EROFS → 具体异常类型）
- **MIME**: 自动通过 `mimetypes.guess_type()` 检测
- **模板方法**: 子类仅需实现 `_resolve_key_to_path(key) -> Path`

### 4.1 LocalStorageBackend (框架层)

- **位置**: `toolkits/storage/local.py`
- **继承**: `BaseFileSystemBackend`
- **用途**: 本地模式（本地部署）、开发环境
- **特有逻辑**: 路径解析（`_resolve_key_to_path`）、写入后设置 chmod 0o600、list 文件列表
- **安全**: `_resolve_key_to_path()` 使用 `os.path.normpath` + `relative_to` 防止路径遍历
- **兼容层**: `backends/storage/local.py` 重导出此实现，保持向后兼容

### 4.2 PersistentStorageBackend (框架层)

- **位置**: `toolkits/storage/persistent.py`
- **继承**: `BaseFileSystemBackend`
- **用途**: Agent-in-Sandbox 容器环境（支持 per-task 和 per-user 模式）
- **特有逻辑**: 双卷路由（`_route_path` + `_resolve_key_to_path`）、幂等 delete、双卷合并 list
- **智能路由**: 根据路径前缀自动分发到 `/persistent/`（长期数据）或 `/workspace/`（临时数据）
- **安全**: 使用 `os.path.normpath` + `relative_to` 防止路径遍历，与 LocalStorageBackend 一致
- **完整实现**: 11/11 `StorageProvider` 接口方法全部实现

### 4.3 S3StorageBackend (业务层)

- **位置**: `app/platform_utils/sandbox/storage.py`（不在框架层）
- **用途**: Sandbox 模式（云部署，如 Cloudflare R2 / AWS S3）
- **注入方式**: 业务层通过 `app/platform_utils/__init__.py` 的 `get_storage_provider()` 按 `DEPLOY_MODE` 选择

### 4.4 SmartCachedStorage (业务层)

- **位置**: `app/core/storage/smart_cache.py`（不在框架层）
- **用途**: 本地缓存 + 远程存储透明同步
- **组合模式**: 包装 `StorageProvider` 实例，添加 LRU 缓存和异步上传队列

---

## 5. 工厂与依赖注入

```python
# 框架层工厂（只创建 LocalStorageBackend）
from myrm_agent_harness.toolkits.storage import create_storage_provider, get_storage_provider

storage = get_storage_provider()  # 延迟初始化的全局单例

# 业务层注入（覆盖框架层默认实现）
from myrm_agent_harness.toolkits.storage import set_storage_provider

set_storage_provider(s3_backend)  # 注入 S3 后端
```

**注入时机**: 业务层在 `app/platform_utils/__init__.py` 中根据 `DEPLOY_MODE` 环境变量决定注入哪个实现。

---

## 6. 存储路径约定

### 6.1 路径结构

```
{base_path}/
├── files/                          # 用户文件
│   └── {user_id}/
│       ├── uploads/{file_id}       # 用户上传
│       ├── generated/{file_id}     # 技能生成
│       └── skill/{file_id}         # 技能包文件
│
├── skills/                         # 技能存储
│   ├── prebuilt/{skill_id}/        # 预构建技能
│   │   ├── SKILL.md
│   │   └── _metadata.json
│   └── local/{skill_id}/           # 本地技能
│
├── users/                          # 用户配置
│   └── {user_id}/
│       └── config/
│           └── skills.json         # 技能配置
│
└── knowledge/                      # 知识库存储
    └── ...
```

### 6.2 路径生成函数

| 函数 | 输出示例 |
|------|----------|
| `get_file_storage_path(uid, fid, UPLOAD)` | `files/{uid}/uploads/{fid}` |
| `get_file_metadata_path(path)` | `{path}.meta.json` |
| `get_skill_storage_path(PREBUILT, sid)` | `skills/prebuilt/{sid}` |
| `get_skill_content_path(path)` | `{path}/SKILL.md` |
| `get_skill_metadata_path(type, sid)` | `skills/{type}/{sid}/_metadata.json` |
| `get_user_config_path(uid, name)` | `users/{uid}/config/{name}.json` |

### 6.3 存储引用 (`@storage:` 协议)

用于容器同步等场景，将存储路径转换为引用格式：

```python
ref = create_storage_ref("files/user123/generated/file_abc")
# → "@storage:files/user123/generated/file_abc"

path = parse_storage_ref(ref)
# → "files/user123/generated/file_abc"
```

---

## 7. 配置

### 7.1 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `MYRM_DATA_DIR` | `~/.myrm` | 全局数据根目录，存储路径自动派生为 `{MYRM_DATA_DIR}/storage` |
| `KnowledgeStorageConfig.size_threshold` | `512000` (500KB) | 知识库混合存储阈值（字节） |

### 7.2 配置类

```python
@dataclass
class StorageConfig:
    mode: StorageMode                    # 始终为 LOCAL（框架层）
    local: LocalStorageConfig            # base_path 配置（从 MYRM_DATA_DIR 派生）
    knowledge: KnowledgeStorageConfig    # 知识库阈值配置
```

路径解析策略：从 `MYRM_DATA_DIR` 环境变量读取根目录，自动派生存储路径。

---

## 8. 类型定义

### FilePurpose (文件用途)

决定文件在 `files/{user_id}/` 下的子目录：

| 枚举值 | 目录 | 说明 |
|--------|------|------|
| `UPLOAD` | `uploads/` | 用户上传的输入文件 |
| `GENERATED` | `generated/` | 技能生成的输出文件 |
| `SKILL` | `skill/` | 技能包内容文件 |

### SkillType (技能类型)

决定技能在 `skills/` 下的子目录：

| 枚举值 | 目录 | 说明 |
|--------|------|------|
| `PREBUILT` | `prebuilt/` | 系统预构建技能 |
| `POOL` | `pool/` | 用户上传技能（内容哈希去重） |
| `LOCAL` | `local/` | 本地文件系统技能 |

---

## 9. 命名规范

| 概念 | 后缀 | 示例 | 说明 |
|------|------|------|------|
| 协议/接口 | `*Provider` | `StorageProvider` | ABC，定义规范 |
| 具体实现 | `*Backend` | `LocalStorageBackend` | 可直接实例化使用 |

---

## 10. 安全设计

### 路径遍历防护

`LocalStorageBackend._resolve_key_to_path()` 和 `PersistentStorageBackend._route_path()` 均实现两层防护：

1. **`os.path.normpath()`**: 规范化路径，处理 `..` 但不跟随符号链接
2. **`full_path.relative_to(base_path)`**: 确保最终路径在允许的根目录内

选择 `normpath` 而非 `resolve()` 是为了避免 `.venv` 等目录中的符号链接导致误报。

### 详细错误报告

`BaseFileSystemBackend._translate_os_error()` 方法基于 `errno` 提供细粒度错误信息（LocalStorageBackend 和 PersistentStorageBackend 均受益）：

| errno | 含义 | 错误消息 |
|-------|------|----------|
| `ENOSPC` | 磁盘空间不足 | No space left on device |
| `ENAMETOOLONG` | 文件名过长 | File name too long |
| `EROFS` | 只读文件系统 | Read-only file system |
| 其他 `OSError` | 通用 I/O 错误 | 包含 errno 编号和描述 |
