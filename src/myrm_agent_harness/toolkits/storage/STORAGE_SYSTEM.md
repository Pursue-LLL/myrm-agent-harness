# 存储系统设计文档

> 最后更新：2026-10-14 | 对应代码版本：当前 `toolkits/storage/` 目录

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
│       └─ 框架层 get_storage_provider()                   │
│          (LocalStorageBackend，根目录 MYRM_DATA_DIR)     │
│                                                          │
│  app/core/storage/service.py                             │
│    └─ FilesService (文件上传/下载/管理)                  │
│                                                          │
│  app/core/skills/store/service.py                        │
│    └─ SkillsService (技能存储管理)                       │
└──────────────────────────┬──────────────────────────────┘
                           │ 依赖方向 ↓
┌──────────────────────────┴──────────────────────────────┐
│ 框架层 (myrm_agent_harness/toolkits/storage/)             │
│                                                          │
│  base.py          → StorageProvider (ABC), FileInfo              │
│  _fs_backend.py   → BaseFileSystemBackend (aiofiles + errno)     │
│  local.py         → LocalStorageBackend (继承 BaseFileSystemBackend) │
│  factory.py       → create/get/set_storage_provider              │
│  config.py        → StorageConfig (存储根目录)                   │
│  types.py         → FilePurpose, SkillType                       │
│  paths.py         → 路径生成工具                                 │
└──────────────────────────────────────────────────────────────┘
```

---

## 3. 核心协议

### 3.1 StorageProvider (ABC)

唯一的存储协议，后端需实现以下抽象方法：

| 方法 | 签名 | 说明 |
|------|------|------|
| `read` | `(key: str) -> bytes` | 读取文件内容 |
| `read_text` | `(key: str, encoding) -> str` | 读取文本文件 |
| `write` | `(key: str, content: bytes, content_type?) -> None` | 写入文件 |
| `write_text` | `(key: str, content: str, encoding?, content_type?) -> None` | 写入文本文件 |
| `delete` | `(key: str) -> None` | 删除文件/目录 |
| `exists` | `(key: str) -> bool` | 检查文件是否存在 |
| `is_dir` | `(key: str) -> bool` | 检查路径是否为目录 |
| `list` | `(prefix?, recursive?) -> list[str]` | 列出文件 |
| `info` | `(key: str) -> FileInfo` | 获取文件元信息 |
| `copy` | `(src_key, dst_key) -> None` | 复制文件/目录 |
| `move` | `(src_key, dst_key) -> None` | 移动文件 |
| `get_url` | `(key: str, expires_in?) -> str` | 获取文件访问 URL |

---

## 4. 实现

### 4.0 BaseFileSystemBackend (框架层基类)

- **位置**: `toolkits/storage/_fs_backend.py`
- **用途**: 文件系统后端的公共基类，提供 aiofiles I/O 和 errno 错误处理的统一实现
- **异步策略**: 读取、文件删除、存在性与元信息查询使用 `aiofiles` / `aiofiles.os`；写入经 `infra.atomic_write.async_atomic_write` 原子落盘；目录删除、`copy`、`move` 经 `asyncio.to_thread` 交给线程池
- **错误处理**: 写入失败时统一按 `errno` 翻译（ENOSPC / ENAMETOOLONG / EROFS → 具体异常类型）
- **MIME**: 自动通过 `mimetypes.guess_type()` 检测
- **模板方法**: 子类仅需实现 `_resolve_key_to_path(key) -> Path`

### 4.1 LocalStorageBackend (框架层)

- **位置**: `toolkits/storage/local.py`
- **继承**: `BaseFileSystemBackend`
- **用途**: 框架唯一内置后端：本地部署、开发环境与云端沙箱（根目录经 `MYRM_DATA_DIR` 指向持久卷）
- **特有逻辑**: 路径解析（`_resolve_key_to_path`）、写入后设置 chmod 0o600、list 文件列表
- **安全**: `_resolve_key_to_path()` 通过 `safe_join_path()` 校验，防止路径遍历与符号链接逃逸（见 §10）

---

## 5. 工厂与依赖注入

```python
# 框架层工厂（按 StorageConfig 创建 LocalStorageBackend）
from myrm_agent_harness.toolkits.storage import create_storage_provider, get_storage_provider

storage = get_storage_provider()  # 延迟初始化的全局单例

# 业务层注入（覆盖框架层默认实现）
from myrm_agent_harness.toolkits.storage import set_storage_provider

set_storage_provider(custom_backend)  # 注入自定义 StorageProvider
```

**注入时机**: 需要自定义后端的业务层在启动时调用 `set_storage_provider`。Server 不覆盖：`app/platform_utils/__init__.py` 的 `get_storage_provider()` 直接返回框架层单例。

---

## 6. 存储路径约定

### 6.1 路径结构

```
{base_path}/
├── files/                          # 文件
│   ├── uploads/{file_id}           # 用户上传
│   ├── generated/{file_id}         # 技能生成
│   └── skill/{file_id}             # 技能包文件
│
├── skills/                         # 技能存储
│   ├── prebuilt/{skill_id}/        # 预构建技能
│   │   ├── SKILL.md
│   │   └── _metadata.json
│   ├── local/{skill_id}/           # 本地技能
│   └── workspace/{skill_id}/       # 工作目录技能
│
└── config/
    └── skills.json                 # 技能配置
```

### 6.2 路径生成函数

| 函数 | 输出示例 |
|------|----------|
| `get_file_storage_path(fid, UPLOAD)` | `files/uploads/{fid}` |
| `get_file_metadata_path(path)` | `{path}.meta.json` |
| `get_skill_storage_path(PREBUILT, sid)` | `skills/prebuilt/{sid}` |
| `get_skill_metadata_path(type, sid)` | `skills/{type}/{sid}/_metadata.json` |
| `get_user_config_path(name)` | `config/{name}.json` |

---

## 7. 配置

### 7.1 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `MYRM_DATA_DIR` | `~/.myrm` | 全局数据根目录，存储路径自动派生为 `{MYRM_DATA_DIR}/storage` |

### 7.2 配置类

```python
@dataclass
class StorageConfig:
    base_path: str  # 存储根目录（从 MYRM_DATA_DIR 派生）
```

路径解析策略：从 `MYRM_DATA_DIR` 环境变量读取根目录，自动派生存储路径。

**单一存储根**：所有存储 key（`files/`、`skills/`、`config/`、`goals/`、`media/` 等）都落在 `{MYRM_DATA_DIR}/storage` 下，路径前缀只决定子目录，存储根仅由 `MYRM_DATA_DIR` 决定。云端沙箱容器的根文件系统只读、仅持久卷可写，部署层把 `MYRM_DATA_DIR` 指向该持久卷；存储层不探测运行环境。

---

## 8. 类型定义

### FilePurpose (文件用途)

决定文件在 `files/` 下的子目录：

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
| `LOCAL` | `local/` | 用户配置路径下扫描到的文件系统技能 |
| `WORKSPACE` | `workspace/` | 工作目录下发现的项目级技能 |

---

## 9. 命名规范

| 概念 | 后缀 | 示例 | 说明 |
|------|------|------|------|
| 协议/接口 | `*Provider` | `StorageProvider` | ABC，定义规范 |
| 具体实现 | `*Backend` | `LocalStorageBackend` | 可直接实例化使用 |

---

## 10. 安全设计

### 路径遍历防护

`LocalStorageBackend._resolve_key_to_path()` 通过 `core.security.path.safe_join_path()` 解析 key：

1. **输入校验**: 拒绝空字节与多行文本内容；key 开头的 `/` 先被去除，按相对路径处理
2. **`os.path.normpath()`**: 得到规范化的虚拟路径（不展开符号链接），Docker 挂载卷与软链接工作区的路径前缀保持不变
3. **`resolve()` + `is_relative_to(base)`**: 用物理路径校验结果仍在根目录内，拦截 `..` 越界与符号链接逃逸

校验失败抛出 `StorageError`。

### 详细错误报告

`BaseFileSystemBackend._translate_os_error()` 在写入失败时基于 `errno` 提供细粒度错误信息：

| errno | 含义 | 错误消息 |
|-------|------|----------|
| `ENOSPC` | 磁盘空间不足 | No space left on device |
| `ENAMETOOLONG` | 文件名过长 | File name too long |
| `EROFS` | 只读文件系统 | Read-only file system |
| 其他 `OSError` | 通用 I/O 错误 | 包含 errno 编号和描述 |
