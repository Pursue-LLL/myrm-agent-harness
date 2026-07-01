# 技能系统设计方案（集大成版 v2）

> 综合 14 个竞品项目（OpenClaw、Clawith、NanoClaw、Nanobot、NextClaw、Deer-Flow、CoPaw、LobsterAI、ironclaw、nexu、picoclaw、nullclaw、zeroclaw、opencode）的最佳实践，
> 基于 myrm-agent-harness 现有架构设计的完整技能系统方案。
>
> 落地状态以本仓实现为准；见 [skills/_ARCH.md](_ARCH.md)。维护者规划笔记在私有 vortexai 开发壳 `temp-docs/`（不在 harness 发行物内）。

---

## 模块总览

| 编号 | 模块 | 分类 | 核心来源 |
|------|------|------|----------|
| 1 | 概述与设计目标 | — | 全部 14 项目共识 |
| 2 | 技能定义规范 | **CORE** | OpenClaw + Deer-Flow + Nanobot |
| 3 | 存储与发现 | **CORE** | ironclaw 三层目录 + 信任分离 |
| 4 | 渐进式加载与 Prompt 生成 | **CORE** | ironclaw XML + LobsterAI 路由 + picoclaw 摘要 |
| 5 | 信任模型与权限衰减 | **CORE** | ironclaw 信任衰减 + opencode 权限过滤 |
| 6 | 确定性技能选择器 | **CORE** | ironclaw 评分 + 排除关键词 + Token 预算 |
| 7 | 依赖检查与可用性 | **CORE** | Nanobot + ironclaw gating |
| 8 | 安全扫描框架 | **CORE** | CoPaw 可扩展框架 + ironclaw 内容转义 |
| 9 | 安装与卸载 | **CORE** | nexu 异步队列 + Deer-Flow 安全提取 |
| 10 | 状态管理 | **CORE** | nexu JSON 账本 + 目录监听 |
| 11 | 语义+环境混合检索 | **CORE** | Hybrid Search (Qdrant + SQLite) |
| 12 | 错误感知型智能隔离 | **CORE** | 1-Strike / 3-Strikes 隔离机制 |
| 13 | 搜索缓存 | **CORE** | picoclaw Trigram Jaccard |
| 14 | Marketplace 集成 | ENHANCE | NextClaw API + CoPaw 多源 |
| 15 | 技能创建与评估 | ENHANCE | Deer-Flow AI 驱动 |
| 16 | Skill Packs 技能集合 | ENHANCE | NanoClaw Flavor + Clawith Template |
| 17 | Curated Skills 预安装 | ENHANCE | nexu |

> **CORE** = 必须实现（竞争力底线），**ENHANCE** = 可选增强。

---

## 1. 概述与设计目标

### 1.1 核心理念

技能（Skill）是 **"AI 的入职指南"** —— 将通用 Agent 变成特定领域的专家。

一个技能本质上是一份结构化的 Markdown 文档（`SKILL.md`），包含：
- **元数据**（YAML frontmatter）：名称、描述、依赖、信任级别等
- **指令正文**（Markdown body）：Agent 执行此技能时遵循的完整指令
- **辅助资源**（可选）：脚本、参考文档、模板等

### 1.2 设计原则

| 原则 | 说明 |
|------|------|
| **安全纵深** | 三层防御：信任衰减（硬限制）+ 安全扫描（软检测）+ 内容转义（注入防护） |
| **渐进式披露** | 只在需要时加载信息，最小化 Token 消耗 |
| **确定性优先** | 技能选择不依赖 LLM，避免循环操纵 |
| **文件即技能** | 一个 `SKILL.md` 就是一个完整的技能定义 |
| **零代码扩展** | 纯 Markdown 即可创建技能，无需编程 |
| **协议驱动** | 通过 Protocol 抽象接口，支持多种后端实现 |

### 1.3 与现有代码的关系

本方案基于 myrm-agent-harness 现有架构，**保留已有优秀设计**，补充和增强：

| 现有模块 | 路径 | 方案中的角色 |
|----------|------|-------------|
| `SkillBackend` Protocol | `backends/skills/protocols.py` | **保留**，作为存储抽象层 |
| `SkillDiscoveryBackend` Protocol | `backends/skills/discovery_protocols.py` | **保留**，作为 Marketplace 抽象层 |
| `SkillWriteBackend` Protocol | `backends/skills/creation_protocols.py` | **保留**，作为技能写入抽象层（save/delete） |
| `SkillMetadata` 数据类 | `backends/skills/types.py`（aggregate；定义见 `types_metadata.py` 等） | **已实现** trust、requires、tool 条件激活等字段 |
| `SkillRegistry` | `agent/skills/runtime/registry.py` | **增强**，集成信任模型和状态管理 |
| `SkillMdLoader` | `agent/skills/runtime/loader.py` | **保留**，三级 Fallback + LRU 缓存已完善 |
| `get_metadata_summary()` | `agent/skills/runtime/registry.py` | **升级**，改为安全 XML 摘要格式 |
| `LocalSkillBackend` | `backends/skills/local.py` | **保留**，映射为 builtin 层（Trusted） |
| `StorageSkillBackend` | `backends/skills/storage.py` | **保留**，映射为 workspace 层（Trusted） |
| `CompositeSkillBackend` | `backends/skills/composite.py` | **保留**，作为路由层 |

**新增模块**：

| 新模块 | 包路径 | 核心来源 |
|--------|--------|----------|
| 信任衰减器 | `agent/skills/security/attenuation.py` | ironclaw |
| 安全扫描器 | `agent/skills/security/scanner.py` | CoPaw |
| 内容转义器 | `agent/skills/security/sanitizer.py` | ironclaw |
| 确定性选择器 | `agent/skills/runtime/selector.py` | ironclaw |
| 依赖检查器 | `agent/skills/runtime/gating.py` | Nanobot + ironclaw |
| Frontmatter 验证器 | `agent/skills/runtime/validator.py` | Deer-Flow |
| 安装队列 | `agent/skills/installer/queue.py` | nexu |
| 安全提取器 | `agent/skills/installer/extractor.py` | Deer-Flow + nexu |
| 状态账本 | `agent/skills/state/ledger.py` | nexu |
| 目录监听器 | `agent/skills/state/watcher.py` | nexu + LobsterAI |
| 搜索缓存 | `agent/skills/search/trigram_cache.py` | picoclaw |
| XML 摘要生成器 | `agent/skills/runtime/prompt.py` | ironclaw + LobsterAI + picoclaw |

---

## 2. 技能定义规范 [CORE]

### 2.1 目录结构

```
skill-name/
├── SKILL.md          (必需) YAML frontmatter + Markdown 指令
├── scripts/          (可选) 可执行脚本 (Python/Bash/Node)
├── references/       (可选) 参考文档，Agent 按需读入上下文
└── assets/           (可选) 输出资源 (模板/图片/字体)
```

**设计决策**：
- 只支持 `SKILL.md` 作为入口文件（14 个项目共识）
- 技能的唯一标识符是**目录名**（kebab-case），不是 frontmatter 中的 `name`

### 2.2 SKILL.md 格式

```markdown
---
name: my-skill
description: 简短描述，用于触发匹配和上下文摘要
version: 1.0.0
category: custom
requires:
  bins: [node, npm]
  env: [API_KEY]
  config: [~/.my-tool/config.json]
tags: [web, automation]
patterns: ["https?://.*\\.example\\.com"]
always: false
exclude-keywords: [unrelated-topic]
max-context-tokens: 8000
---

# 技能标题

## 指令正文
（Agent 触发此技能后读取的完整指令，建议 <500 行）
```

### 2.3 Frontmatter 字段完整列表

| 字段 | 类型 | 必需 | 说明 | 来源 |
|------|------|------|------|------|
| `name` | string | 推荐 | 技能名称（显示用，实际标识用目录名） | OpenClaw |
| `description` | string | **必需** | 简短描述（≤1024 字符），用于摘要和触发匹配 | 全部 |
| `version` | string | 可选 | 语义化版本号 | OpenClaw + CoPaw |
| `category` | enum | 可选 | `builtin` / `custom`，默认 `custom` | Deer-Flow |
| `requires` | object | 可选 | 依赖声明（见 §7） | Nanobot + ironclaw |
| `requires.bins` | string[] | 可选 | 需要的 CLI 工具 | Nanobot |
| `requires.env` | string[] | 可选 | 需要的环境变量 | Nanobot |
| `requires.config` | string[] | 可选 | 需要的配置文件路径 | ironclaw |
| `tags` | string[] | 可选 | 分类标签（用于搜索、过滤、选择器匹配） | NextClaw + ironclaw |
| `always` | boolean | 可选 | 是否始终加载到系统 Prompt（默认 `false`） | Nanobot |
| `hooks` | object[] | 可选 | Hook 定义（事件触发） | 现有架构 |
| `allowed-tools` | string[] | 可选 | 允许使用的工具白名单 | 现有架构 |
| `patterns` | string[] | 可选 | 正则模式（精确匹配 URL/路径等格式） | ironclaw |
| `exclude-keywords` | string[] | 可选 | 排除关键词（防止误触发） | ironclaw |
| `max-context-tokens` | int | 可选 | 最大上下文 Token 数（默认 8000） | ironclaw |
| `license` | string | 可选 | 许可证 | agentskills.io |
| `compatibility` | string | 可选 | 环境要求（≤500 字符） | agentskills.io |
| `metadata` | object | 可选 | 扩展元数据（author、homepage 等） | agentskills.io |

**命名规范**（来自 Deer-Flow 验证器）：
- 技能目录名：kebab-case，`^[a-z][a-z0-9-]*$`，最长 64 字符
- description：禁止包含 `<` `>` 角括号，最长 1024 字符
- Frontmatter 字段：白名单验证，未知字段产生警告

**关键设计决策**：
- `requires` 采用 Nanobot 的结构化格式 + ironclaw 的 `config` 扩展，支持自动化检查
- `exclude-keywords` 和 `max-context-tokens` 来自 ironclaw，用于确定性选择器
- `always` 来自 Nanobot，支持"始终加载"的特殊技能（如 memory）

---

## 3. 存储与发现 [CORE]

### 3.1 三层目录结构 + 信任分离

```
skills/
├── builtin/              # 内置技能（随项目发布，只读）→ Trust: Trusted
│   ├── memory/
│   │   └── SKILL.md
│   └── web-search/
│       └── SKILL.md
├── workspace/            # 用户本地技能（可读写）→ Trust: Trusted
│   └── my-custom-skill/
│       ├── SKILL.md
│       └── scripts/
└── installed/            # 外部安装技能（Marketplace/GitHub）→ Trust: Installed
    └── some-community-skill/
        └── SKILL.md
```

**优先级规则**：workspace > builtin > installed（同名技能，高优先级覆盖低优先级）

**信任分离**（来自 ironclaw）：
- `builtin/` 和 `workspace/` 中的技能自动获得 `Trusted` 信任级别
- `installed/` 中的技能自动获得 `Installed` 信任级别（受限）
- **物理目录决定信任级别**，无法通过 frontmatter 自行声明

**设计决策**：
- 采用 ironclaw 的三层方案 + 信任分离，比两层方案多一层安全保障
- `installed/` 层的技能受权限衰减约束（见 §5），只能使用只读工具
- 用户可以将 `installed/` 中信任的技能手动移到 `workspace/` 来提升信任
- builtin 对应 `LocalSkillBackend`，workspace/installed 对应 `StorageSkillBackend`
- 通过 `CompositeSkillBackend` 实现路由和优先级

### 3.2 存储抽象层

现有 `SkillBackend` Protocol 已提供完善的抽象，**无需修改**。

### 3.3 技能发现

现有 `SkillDiscoveryBackend` Protocol 已定义搜索和安装接口，**无需修改**。

---

## 4. 渐进式加载与 Prompt 生成 [CORE]

### 4.1 四级加载策略

```
Level 0: 发现（Discovery）
  → list_skills() 返回所有技能的 SkillMetadata
  → 用于初始化时构建技能索引
  → 同时执行依赖检查和信任级别标注

Level 1: 摘要（Summary）
  → generate_skill_prompt() 生成安全 XML 摘要
  → 注入系统 Prompt，供 LLM 了解可用技能
  → Token 消耗：~50 tokens/技能

Level 2: 正文（Body）
  → get_skill_content() 返回 SKILL.md 正文
  → LLM 选择使用某技能后按需加载
  → Token 消耗：~500-2000 tokens/技能

Level 3: 资源（Resources）
  → get_skill_resources() 返回脚本/参考文档
  → 技能执行过程中按需加载
  → Token 消耗：按需
```

### 4.2 安全 XML 摘要格式

**融合 ironclaw 内容转义 + LobsterAI 路由指令 + picoclaw XML 结构**：

```xml
<available_skills>
  <routing_rules>
    If exactly one skill clearly applies to the user's request: read its SKILL.md.
    If multiple skills may apply: ask the user which to use.
    If no skill applies: proceed without skills.
  </routing_rules>

  <skill name="web-search" available="true" trust="trusted" location="builtin/web-search/SKILL.md">
    <description>Search the web for real-time information</description>
    <tags>search, web</tags>
  </skill>

  <skill name="database-query" available="false" trust="trusted" location="workspace/database-query/SKILL.md">
    <description>Query SQL databases</description>
    <requires>
      <bin>psql</bin>
      <env>DATABASE_URL</env>
    </requires>
    <unavailable_reason>Missing: psql binary, DATABASE_URL env var</unavailable_reason>
  </skill>

  <skill name="community-tool" available="true" trust="installed" location="installed/community-tool/SKILL.md">
    <description>A community-contributed tool</description>
  </skill>

  <skill name="memory" available="true" trust="trusted" always="true" location="builtin/memory/SKILL.md">
    <description>Persistent memory across conversations</description>
  </skill>
</available_skills>
```

**关键安全措施**（来自 ironclaw）：
- 所有 XML 属性值经过转义（`<`, `>`, `&`, `"`, `'`）
- `<skill>` 标签逃逸检测（大小写不敏感，处理空白和 NUL 字节）
- 行尾规范化确保一致性哈希

**路由指令**（来自 LobsterAI）：
- 显式告诉 LLM 如何选择技能，减少误触发
- `trust` 属性让 LLM 知道技能的信任级别

**设计决策**：
- 默认使用完整 XML 格式
- 技能数量 >30 时自动切换 Compact 模式（缩短属性名）
- `location` 属性提供文件路径，LLM 可直接读取

### 4.3 Always 技能

标记 `always: true` 的技能，其完整正文（Level 2）始终注入系统 Prompt。

**约束**：
- Always 技能数量应控制在 1-3 个（避免 Token 爆炸）
- 典型 Always 技能：memory（持久记忆）、core-policies（核心策略）

### 4.4 缓存策略

现有 `SkillMdLoader` 已实现 LRU 缓存 + 三级 Fallback + 可观测性，**无需修改**。

---

## 5. 信任模型与权限衰减 [CORE]

### 5.1 信任级别

| 级别 | 目录 | 含义 |
|------|------|------|
| `Trusted` | `builtin/`, `workspace/` | 用户明确信任的技能，可使用所有工具 |
| `Installed` | `installed/` | 外部安装的技能，只能使用只读工具 |

### 5.2 权限衰减机制（来自 ironclaw）

**核心规则**：当多个技能同时激活时，**最低信任级别决定工具上限**。

```
场景 1: 只有 Trusted 技能激活
  → 所有工具可用

场景 2: 有任何 Installed 技能激活
  → 只有只读工具可用（read_file, list_dir, search, ...）
  → 写入工具被移除（write_file, execute_command, ...）
  → LLM 看不到被移除的工具定义（无法被 Prompt 注入绕过）
```

**只读工具白名单**（Installed 技能可用）：
- `read_file`, `list_dir`, `search`, `grep`
- `get_skill_content`, `list_skill_resources`

**关键安全特性**：
- LLM **看不到**被移除的工具定义，从根本上防止 Prompt 注入绕过
- 信任级别由物理目录决定，技能自身无法声明更高信任
- 用户可以通过移动技能目录来提升/降低信任

### 5.3 Agent 级别权限过滤（来自 opencode）

除了信任衰减，还支持 Agent 级别的技能可见性过滤：

- 不同 Agent 可以配置不同的技能权限
- `available(agent)` 方法根据 Agent 权限过滤可用技能列表
- 被 deny 的技能不会出现在 XML 摘要中

**设计决策**：
- 2 个信任级别足够覆盖所有场景（Trusted vs Installed）
- 最低信任原则从根本上防止权限升级
- 不采用更多级别（如 CoPaw 的 block/warn/off），因为硬限制比软警告更安全
- Agent 权限过滤是额外的细粒度控制层

---

## 6. 确定性技能选择器 [CORE]

### 6.1 设计理念（来自 ironclaw）

技能选择的第一阶段是**纯确定性的**，不依赖 LLM：
- 防止 LLM 被 Prompt 注入操纵选择恶意技能
- 评分有上限，防止技能通过堆砌关键词刷分
- 排除关键词提供否决机制

### 6.2 评分机制

```
总分 = keyword_score + tag_score + pattern_score

keyword_score（上限 0.6）：
  - 精确匹配：+0.3/次
  - 子串匹配：+0.1/次

tag_score（上限 0.3）：
  - 标签匹配：+0.15/次

pattern_score（上限 0.3）：
  - 正则模式匹配（frontmatter `patterns` 字段）：+0.15/次
  - 用于精确匹配 URL、文件路径、代码片段等结构化输入
```

### 6.3 排除关键词（Veto 机制）

如果用户消息包含技能的 `exclude-keywords` 中的任何词，该技能直接排除（得分归零）。

### 6.4 Token 预算控制

- 每个技能声明 `max-context-tokens`（默认 8000）
- 加载时验证：如果技能正文估算 Token 数超过 `max-context-tokens * 2`，拒绝加载
- 选择多个技能时，总 Token 不超过上下文窗口的 50%

### 6.5 选择流程

```
1. 收到用户消息
2. 对所有 enabled 且 available 的技能计算评分
3. 排除关键词否决
4. 按分数排序，取 Top-N（默认 N=3）
5. Token 预算裁剪
6. 返回选中技能列表
```

**设计决策**：
- 确定性选择器是第一道防线，LLM 只在第二阶段参与（从候选中精选）
- 评分上限防止技能通过堆砌关键词/标签刷分
- 排除关键词防止跨领域技能干扰（如 "python" 技能不应被 "python snake" 触发）

---

## 7. 依赖检查与可用性 [CORE]

### 7.1 依赖类型（融合 Nanobot + ironclaw）

| 类型 | 声明方式 | 检查方法 | 来源 |
|------|----------|----------|------|
| CLI 工具 | `requires.bins: [node, npm]` | `shutil.which()` | Nanobot |
| 环境变量 | `requires.env: [API_KEY]` | `os.environ.get()` | Nanobot |
| 配置文件 | `requires.config: [~/.tool/config.json]` | `Path.exists()` | ironclaw |

### 7.2 检查时机

- **Level 0（发现）**：`list_skills()` 时执行依赖检查，结果缓存到 `SkillMetadata.available`
- **Level 1（摘要）**：XML 摘要中标注 `available` 和 `unavailable_reason`
- **Level 2（正文）**：不可用技能仍可加载正文（LLM 可引导用户安装依赖）

### 7.3 异步检查（来自 ironclaw）

所有检查异步执行，避免阻塞主流程：
- `bins` 检查通过 `asyncio.to_thread(shutil.which, ...)` 执行
- 结果缓存，不重复检查（除非手动刷新）

**设计决策**：
- 不可用技能不会从列表中隐藏，而是标注原因（LLM 可引导用户安装依赖）
- `config` 类型是 ironclaw 的独特贡献，用于检查配置文件是否存在
- 异步检查确保大量技能时不阻塞启动

---

## 8. 安全扫描框架 [CORE]

### 8.1 架构（来自 CoPaw，精简版）

```
Scanner（编排器）
  ├── PatternAnalyzer（正则模式分析）
  ├── ContentSanitizer（内容转义，来自 ironclaw）
  └── ScanPolicy（可配置策略）
```

### 8.2 威胁类别（26 类 108 模式）

| 类别 | 说明 | 模式数 |
|------|------|--------|
| `prompt_injection` | Prompt 注入攻击（含 DAN/jailbreak/HTML 注入） | 12 |
| `command_injection` | 命令注入 | 4 |
| `credential_exposure` | 凭据泄露（含 GitHub/OpenAI/Anthropic/AWS token） | 7 |
| `data_exfiltration` | 数据外泄（含 env dump/context exfil/markdown exfil） | 10 |
| `filesystem_access` | 敏感文件访问 | 2 |
| `process_operation` | 进程操作 | 4 |
| `network_access` | 网络访问（含隧道服务/paste 站点） | 7 |
| `screen_input` | 屏幕/输入捕获 | 2 |
| `memory_config_snooping` | 内存/配置窥探 | 4 |
| `code_injection` | 代码注入 | 4 |
| `privilege_escalation` | 权限提升（含 NOPASSWD/SUID） | 5 |
| `environment_manipulation` | 环境变量操纵 | 3 |
| `reflection` | 反射/元编程 | 3 |
| `deserialization` | 反序列化攻击 | 3 |
| `log_audit_tampering` | 日志/审计篡改 | 2 |
| `scheduled_task_injection` | 定时任务注入 | 2 |
| `container_escape` | 容器逃逸 | 2 |
| `memory_manipulation` | 内存操纵 | 2 |
| `dns_tunneling` | DNS 隧道 | 2 |
| `supply_chain` | 供应链攻击 | 5 |
| `obfuscation` | 代码混淆 | 7 |
| `destructive` | 破坏性操作 | 3 |
| `persistence` | 持久化（含 agent config 劫持） | 4 |
| `path_traversal` | 路径穿越 | 3 |
| `crypto_mining` | 加密货币挖矿 | 1 |
| `reverse_shell` | 反向 Shell | 5 |

扫描器还包含 LLM 二次审计能力（可选），通过 `SkillLLMAuditor` 提供语义级威胁检测，遵循"只升不降"原则。

**设计决策**：
- 模式定义独立于扫描逻辑（`patterns.py` vs `scanner.py`），便于扩展
- 扫描结果缓存（基于 mtime + 内容 SHA-256 哈希）
- LLM 审计为可选增强，无 LLM 时 graceful fallback 到纯正则

### 8.3 内容转义（来自 ironclaw）

所有技能内容在注入 Prompt 前经过转义：
- XML 属性转义（`<`, `>`, `&`, `"`, `'`）
- `<skill>` 标签逃逸检测（大小写不敏感，处理空白和 NUL 字节）
- 行尾规范化（统一为 `\n`）确保一致性哈希

### 8.4 安装前扫描 + 用户确认（来自 LobsterAI）

- 安装外部技能前自动执行安全扫描
- 如果检测到风险，暂停安装并提示用户确认
- 用户可选择：安装、安装但禁用、取消
- 待确认的安装有 TTL（5 分钟），超时自动取消

### 8.5 内容完整性哈希（来自 ironclaw）

每个技能的 SKILL.md 计算 SHA-256 内容哈希：
- 行尾规范化后计算（`\r\n` → `\n`），确保跨平台一致性
- 用途：白名单精确匹配、篡改检测、缓存失效判断、变更检测
- 哈希存储在状态账本中，每次加载时比对

### 8.6 白名单机制（来自 CoPaw）

- 已确认安全的技能可加入白名单（技能名 + 内容 SHA-256 哈希）
- 白名单中的技能跳过扫描
- 内容变更后哈希失效，需重新扫描

**设计决策**：
- 安全扫描是 CORE 而非 ENHANCE，因为这是生产级系统的底线
- 不采用 CoPaw 的全部 17 种威胁类别，避免过度设计
- 内容转义是独立于扫描的必要措施（即使扫描通过，也要转义）
- 白名单 + SHA-256 哈希确保效率和安全的平衡
- 行尾规范化确保跨平台一致性哈希（ironclaw 验证有效）

---

## 9. 安装与卸载 [CORE]

### 9.1 安装方式

| 方式 | 场景 | 信任级别 | 来源 |
|------|------|----------|------|
| **目录复制** | 开发环境、本地技能 | Trusted（workspace） | Nanobot |
| **.skill 归档** | Marketplace 分发 | Installed | Deer-Flow |
| **Git URL** | GitHub/GitLab 仓库 | Installed | NextClaw + picoclaw |
| **Marketplace API** | 在线商店 | Installed | NextClaw |

### 9.2 异步安装队列（来自 nexu）

**核心特性**：
- 状态机：`queued` → `downloading` → `installing-deps` → `done` / `failed`
- 并发控制：`asyncio.Semaphore`（默认 max_concurrency=2）
- 智能 Rate Limit 处理：解析错误消息中的 `retry in Xs`，暂停队列并重试
- 取消支持：pending 任务直接移除，active 任务标记取消
- 去重：同一技能不重复入队
- 自动清理：完成的任务在一定时间后从队列移除

**Rate Limit 处理流程**：
```
1. 安装失败，错误消息包含 "retry in 30s"
2. 解析出暂停时长 30s
3. 暂停整个队列 30s
4. 重试失败的任务（最多 3 次）
5. 超过重试次数则标记为 failed
```

### 9.3 安全提取（来自 Deer-Flow + nexu）

`.skill` 文件是标准 ZIP 归档。安全提取防护措施：
- 路径穿越检查（绝对路径、`../` 组件、Windows 驱动器前缀）
- 符号链接跳过
- Zip Bomb 防御（总大小 50MB、文件数 500、单文件 10MB）
- 使用 staging 目录提取，验证通过后原子移动到目标位置
- Frontmatter 验证
- 安全扫描（§8）

### 9.4 npm 依赖自动安装（来自 nexu）

如果技能目录中存在 `package.json`，自动执行依赖安装。

### 9.5 版本比较与自动升级（来自 CoPaw）

- builtin 技能的 frontmatter 中有 `version` 字段
- 启动时比较 builtin 版本与 workspace 中的覆盖版本
- 如果 builtin 版本更新，提示用户是否升级（不自动覆盖）
- 使用语义化版本比较（`packaging.version.Version`）

### 9.6 卸载流程

- 仅允许卸载 `workspace/` 和 `installed/` 层的技能
- `builtin/` 技能不可卸载
- 卸载后更新状态账本（§10）

**设计决策**：
- 异步队列是生产级必备（防止同时安装 100 个技能压垮系统）
- Rate Limit 处理是与外部 API 交互的必备能力（nexu 独有）
- staging 目录 + 原子移动确保安装的原子性（nexu）
- 安装到 `installed/` 目录自动获得 Installed 信任级别

---

## 10. 状态管理 [CORE]

### 10.1 JSON 账本系统（来自 nexu）

使用 JSON 文件作为技能状态的单一事实来源：

```json
{
  "version": 1,
  "skills": {
    "web-search": {
      "enabled": true,
      "installed_at": "2025-01-15T10:30:00Z",
      "source": "builtin"
    },
    "community-tool": {
      "enabled": true,
      "installed_at": "2025-03-20T14:00:00Z",
      "source": "clawhub",
      "install_url": "https://clawhub.io/skills/community-tool"
    }
  }
}
```

**文件路径**：`~/.myrm/skills_ledger.json`

### 10.2 原子写入

- 写入 `.tmp` 文件 → `os.rename()` 原子替换
- 确保断电/崩溃时不会损坏账本
- Pydantic 模型验证，格式错误时回退到空账本

### 10.3 目录监听 + 双向同步（来自 nexu + LobsterAI）

使用 `watchdog` 库监听技能目录变更：
- 新增 `SKILL.md` → 自动注册到账本（标记为 `managed`）
- 删除技能目录 → 自动标记为 `uninstalled`
- 防抖（500ms）避免频繁触发
- 与安装队列协同：正在安装的技能不触发同步

**双向同步**：
- 磁盘 → 账本：新发现的技能自动记录
- 账本 → 磁盘：账本中存在但磁盘缺失的技能标记为已卸载

### 10.4 极速热重载与增量同步 (Hot Reload)

系统支持极速热重载与增量同步，确保技能变更实时生效，同时保持极低的性能开销：

- **O(N) 快照读取**：Agent 执行时直接读取 SQLite 快照中预解析的元数据，避免重复文件 I/O 和 frontmatter 解析。性能基准测试显示：
  - 10 技能：3.8ms
  - 200 技能：68.7ms
  - 随规模增长加速比提升，在网络文件系统或容器环境中优势更明显

- **O(1) 精准增量更新**：
  - **本地开发模式**：启动 `SkillWatcher`（基于 watchdog）监听外部编辑器修改，自动 debouncing 并触发精准更新。100 个技能中修改 1 个，仅需 5.8ms。
  - **SaaS 模式**：可通过 API 触发 `snapshot.upsert_from_path` 实现零监听开销。

- **O(N) 增量冷启动同步**：启动时执行 `sync_all()`，仅通过 `os.stat` 检查 `file_mtime`，只重新解析有变动的文件。

**技术细节**：
- SQLite WAL 模式支持多读单写并发
- 基于 `file_mtime` 的增量同步避免全量扫描
- Cursor 显式关闭防止资源泄漏
- Debouncing 机制（0.5秒窗口）批量处理快速连续变化

**设计决策**：
- 采用混合架构（API 主动触发 + 本地按需监听），兼顾 SaaS 大规模部署的资源节约和本地开发的实时热重载体验
- 快照存储完整 content，支持离线查询，无需回读文件
- Agent 层不缓存技能列表，确保"文件即真相"，避免状态不一致

---

## 11. 语义+环境混合检索 (Hybrid Retrieval) [CORE]

### 11.1 架构设计
系统采用 **Qdrant (语义向量) + SQLite (关系型元数据)** 的混合检索架构，以解决传统纯关键字搜索（LIKE）在自然语言查询下的低召回率问题。

**核心机制**：
- **同步双写 (Synchronous Dual-Write)**：在 `SkillStore.save_skill` 时，将技能文本（名称+描述+内容+陷阱）向量化后写入 Qdrant，同时将核心元数据（`is_active`, `os_platform`）作为 Payload 写入。
- **Payload 预过滤 (Pre-filtering)**：在 Qdrant 查询阶段，直接利用 Payload 过滤非活跃技能和不匹配当前操作系统的技能，避免向量检索后在 SQLite 中被大量过滤导致召回不足。
- **SQLite 后置精确过滤 (Post-filtering)**：Qdrant 返回 Top-K 结果后，在 SQLite 中进行最终的精确过滤（如 `min_effective_rate` 成功率阈值），确保返回的技能不仅语义相关，而且质量达标。
- **优雅降级 (Graceful Fallback)**：如果 Qdrant 服务不可用或向量化失败，系统自动无缝降级到原有的 SQLite `LIKE` 关键字检索，确保核心功能不中断。

### 11.2 启动对齐与自愈 (Startup Reconciliation)
为了解决本地 SQLite 和 Qdrant 之间可能出现的数据不一致（如崩溃、异常关机），系统实现了 `sync_vectors` 启动对齐机制：
- 在系统启动时，读取 SQLite 中所有活跃的技能。
- 批量向量化并 Upsert 到 Qdrant 中。
- 确保向量库始终反映最新的本地技能状态。

---

## 12. 错误感知型智能隔离 (Error-Aware Smart Quarantine) [CORE]

### 12.1 核心理念
解决 Agent 固执调用损坏技能导致的“死循环”问题。摒弃竞品（如 EvoMap, ironclaw）复杂的数学衰减公式，采用极简的字符串匹配和计数器，实现精准打击与零误杀。

### 12.2 隔离策略
- **一击必杀 (1-Strike)**：如果错误信息包含确定性的代码级错误（如 `SyntaxError`, `ModuleNotFoundError`, `command not found`），第一次失败即触发硬隔离（`is_active=False`），避免白白浪费重试 Token。
- **容错隔离 (3-Strikes)**：如果错误是网络超时、API 限流等非确定性错误，给予网络抖动容错空间，连续失败 3 次才触发硬隔离。

### 12.3 效果与自愈
被硬隔离的技能会瞬间从 Agent 的可用工具列表中消失，迫使 Agent 切换策略。同时，该技能仍会被送入后台 FIX 引擎。修复成功后，新版本将作为活跃技能重新上线，实现系统的自我愈合。

---

## 13. 搜索缓存 [CORE]

### 12.1 Trigram Jaccard 相似度缓存（来自 picoclaw）

**核心思想**：相似的搜索查询应该返回相似的结果，无需重复调用 API。

**算法**：
1. 将查询字符串分解为 trigrams（3 字符滑动窗口）
2. 对 trigrams 计算哈希（uint32）以节省内存
3. 新查询与缓存中所有查询计算 Jaccard 相似度
4. 相似度 ≥ 0.7 → 缓存命中，直接返回结果
5. 相似度 < 0.7 → 缓存未命中，执行实际搜索并缓存结果

**缓存策略**：
- LRU 淘汰（最大 100 条）
- TTL 过期（5 分钟）
- 线程安全（`threading.Lock`）

**效果**：
- "web search tool" 和 "web searching tools" 的 Jaccard 相似度 > 0.7 → 缓存命中
- 显著减少对 Marketplace API 的重复调用

**设计决策**：
- 在所有 14 个项目中，只有 picoclaw 实现了这种搜索缓存，是我们的差异化优势
- 算法简单高效，无额外依赖
- 阈值 0.7 经过 picoclaw 验证，平衡了命中率和准确率

---

## 14. Marketplace 集成 [ENHANCE]

### 17.1 多源聚合搜索（来自 CoPaw + picoclaw）

支持多个技能源的并发搜索：
- ClawHub（官方商店）
- GitHub（仓库搜索）
- skills.sh（在线目录）
- 本地索引

**并发策略**（来自 picoclaw）：
- 使用 `asyncio.gather()` 并发查询所有源
- 每个源有独立超时（60s）
- 支持部分成功（至少一个源返回结果即可）
- 结果按评分排序后合并去重

### 12.2 统一 API（来自 NextClaw）

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/skills` | GET | 列出已安装技能（含状态） |
| `/api/skills/search` | GET | 搜索 Marketplace |
| `/api/skills/{name}` | GET | 技能详情 |
| `/api/skills/{name}/content` | GET | SKILL.md 正文 |
| `/api/skills/install` | POST | 安装技能（入队） |
| `/api/skills/{name}` | DELETE | 卸载技能 |
| `/api/skills/{name}/enable` | PUT | 启用/禁用技能 |
| `/api/skills/queue` | GET | 安装队列状态 |

### 12.3 多语言支持（来自 NextClaw + nexu）

- 技能描述支持 `description`（英文）和 `descriptionZh`（中文）
- 内置标签翻译表（110+ 标签，来自 nexu）
- 前端根据用户语言偏好自动选择

### 12.4 GitHub 智能安装（来自 picoclaw + CoPaw）

- 智能 URL 解析：完整 URL、`owner/repo`、`owner/repo/path`、分支/标签/commit 引用
- 两级下载策略：GitHub Contents API（优先）→ `raw.githubusercontent.com`（降级）
- 多分支/路径模糊匹配搜索 `SKILL.md`（来自 CoPaw）

**设计决策**：
- Marketplace 是增强模块，不影响核心功能
- 并发搜索 + Trigram 缓存确保搜索性能
- 安装通过异步队列（§9.2），不阻塞 UI

---

## 13. 技能创建与评估 [ENHANCE]

### 13.1 自动技能提炼与“无状态目标感知滚动窗口” (Stateless Goal-Aware Tumbling Window)

系统支持**真·自动进化**能力，彻底抛弃了低效的全量人工介入草稿确认流程，并从根本上解决了长会话提炼引发的“提炼幻觉（Context Noise）”问题。

```
1. 目标感知拦截 (Goal-Aware Slicing) → 在 StreamExecutor 主执行循环中，维护一个零内存占用的游标 `last_extracted_idx`。
   - 当检测到当前任务的 `GoalExecutionSummary` 为完成状态，或遇到 SubAgent 退出等“语义边界”时。
   - 或作为兜底保障，当累计工具调用次数达到 15 次（15-Call Sliding Window）时。
   系统瞬间切断这一段高内聚的执行轨迹游标 `(start_idx, end_idx)`。
2. 零阻塞后台入队 (Zero-Blocking Dispatch) → 将切片游标作为 `TRACE_SLICE_READY` Hook 抛出，异步压入后台队列，主 Agent 继续对话毫无感知。
3. 数据库游标回拉与 0 成本 AST 分析 → 
   - 后台 Worker (TraceAnalyzer) 根据游标去 SQLite 捞出对应的 Trace 日志。
   - 引入 AST-Aware Static Analyzer，直接评估该切片是否闭环（比如如果切片中全是在报错死循环，直接丢弃），实现 0 Token 成本的垃圾拦截。
4. LLM 提炼与事件解耦 (Event-Driven Decoupling) →
   - 提取出可复用的套路 (EvolutionProposal)。
   - 不再越权直接写库，而是附带出错时的 `Agent_ID`，封装进 `IdleTaskProgressEvent` 广播。
5. 显式审批与负反馈闭环 (Explicit Approval & Negative Exemplars) → 
   - Server 业务层捕获事件，落库为 `ApprovalRecord` 草稿。
   - 前端 GUI 专属 Inbox 亮起红点，等待用户显式 Approve。保护了系统 Prompt Cache 不被后台提炼静默击穿。
   - 如果用户 Reject，不仅删除草稿，还会写入记忆库的负面样本集（Negative Exemplars），防止未来引擎重复提炼相同废料。
```

**设计决策**：
- 在后台进程全自动完成提取与重构，实现真正的无感进化，同时用沙箱预演和对抗性模糊测试彻底堵死知识库污染漏洞。
- 采用模糊匹配补丁机制（7级匹配策略），精准将 LLM 修改映射回 SKILL.md。
- 直接持久化到文件系统，部分替代依赖于通知系统的 Draft 草稿审批流，大幅提升真实系统的自动化自愈能力。

### 13.2 错误感知型智能拦截与 GUI-First 强制重试 (Error-Aware Static Interception & GUI-First Force Retry)

为了防止自动进化陷入“死循环”并优化 LLM 调用成本，系统在进化管线前端实现了轻量级静态拦截与 GUI 驱动的强制重试机制：

- **静态错误拦截 (Static Interception)**：在调用 LLM 确认错误前，通过正则表达式提取异常类型。如果检测到明确的语法或导入错误（如 `SyntaxError`, `ModuleNotFoundError`, `IndentationError`），则直接绕过 LLM 确认，允许进化（0 成本，极速响应）。
- **GUI-First 强制重试 (GUI-First Force Retry)**：默认情况下，进化失败的技能会进入冷却期（如 1 小时）。摒弃脆弱的多语言正则匹配，系统在前端“技能成长审计 (Evolution Rejection Dashboard)”提供明确的“强制重试”按钮。用户点击后，通过 API 传递结构化的 `force_retry=True` 标志，确定性地打破冷却锁，立即重试进化，实现防雪球与用户意图的完美平衡，且完全符合 GUI-First 原则。

### 17.2 技能进化锁定保护 (File-backed Evolution Lock)

为了解决真·自动进化机制可能带来的用户体验痛点（如：用户精心手动编辑修复的技能代码被后续基于错误反馈触发的自动进化覆盖），技能系统实现了**文件级双向进化锁定**架构。

**核心机制**：
- `evolution_locked`：一个布尔状态锁。该状态**直接作为 YAML Frontmatter 元数据** (`evolution_locked: true`) 存储在 `SKILL.md` 物理文件中。
- **文件即真相 (File-as-Truth)**：确保极客用户在本地离线修改或通过 Zip 分享技能时，锁状态伴随文件终身有效，避免由于仅存储在数据库中导致的脱节覆盖。
- **双向同步写入**：通过 API (`/skills/{skill_id}/evolution-lock`) 切换状态时，系统会同时更新 SQLite 缓存账本（用于极速查询）并物理复写 `SKILL.md` 的 YAML 头部。
- **EvolutionScreener 拦截 (双重纵深防御)**：
  1. **Phase 0 DB Check**：查询 SQLite 中 `store.is_evolution_locked`（极速零开销阻断）。
  2. **Phase 0 File Check**：回退检查底层解析的 `SkillMetadata.evolution_locked`，防范文件被本地手动加锁后数据库未同步的情况。
- **防覆盖保护**：不论是 FIX 还是 DERIVED 进化，锁定状态均作为防御纵深，确保持久化内容绝对不会被修改，将代码控制权完全交还给用户。

### 14.3 语义去重防御 (Semantic Deduplication)

随着技能数量增长，功能相似但名称不同的 skill 会不断累积（"Skill 熵增"），导致 Agent 变慢变笨。
系统实现了三层纵深防御来防止语义级重复：

**三层防御架构**：

```
第 1 层（软）: reviewer prompt → 传入全量 skill 目录 → LLM 自主判断转 patch
第 2 层（硬）: growth_lifecycle → 代码级语义搜索 → 高相似度 draft 降级为人工审核
第 3 层（硬）: manage_tool → 相似度警告 → Agent 可感知并选择 patch 而非创建新 skill
```

**核心组件**：
- `SkillSimilarityChecker` Protocol（框架层）：定义语义相似度检查接口
- `HybridSimilarityChecker`（业务层）：基于 HybridSkillSearchEngine（BM25+Embedding）实现
- `_check_similarity()`（框架层 manage_tool）：save 操作时返回相似度警告
- `_check_semantic_duplicate()`（业务层 growth_lifecycle）：自动复盘时拦截重复 draft

**设计决策**：
- 所有层均为可选注入（`None` 默认值），不影响已有逻辑
- 失败时静默降级（try/except + warning log），绝不阻塞正常流程
- 不阻断创建，只提供信息让 Agent 或人工审核做最终决策

### 13.4 多智能体技能池与按需加载 (Multi-Agent Skill Pool & On-Demand Loading)

在 Agent in Sandbox 架构下，每个用户拥有完全物理隔离的私有沙箱与持久化存储。智能体的技能管理遵循**私有技能池与按需配置**的极简原则。

**核心机制**：
- **沙箱私有技能池 (Sandbox Private Skill Pool)**：无论是用户批量导入的技能包，还是智能体自动提取进化出的技能，均统一保存在用户专属沙箱底层的技能库中。
- **零技能初始状态 (Zero-Skill Initialization)**：新建的智能体初始配置不包含任何技能（`AgentRuntimeSpec.skill_ids = []`）。底层 Factory 层严格遵循透传此配置，确保全新智能体以 0 技能启动，杜绝全局污染和提示词缓存命中率下降。
- **按需显式装载 (Explicit On-Demand Loading)**：多智能体的能力差异和隔离完全由配置驱动。用户在前端 GUI 为不同的智能体显式分配所需的技能 ID。运行时 `SkillAgent` 仅精准加载被显式选中的技能，实现能力的逻辑隔离。

**设计决策**：
- 坚持"奥卡姆剃刀"原则。智能体实例的 `skill_ids` 列表是定义其能力边界的唯一事实来源 (Single Source of Truth)。`scope_agent_id` 用于进化审核时标记技能的归属智能体（写入 frontmatter 和 SQL 查询过滤），但不影响技能的物理存储或全局池结构。
- 彻底拥抱 GUI-First，跨越智能体的能力复用与组合完全通过前端界面直观配置，所见即所得。

---

## 14. Skill Packs 技能集合 [ENHANCE]

### 17.1 定义（来自 NanoClaw Flavor + Clawith Agent Template）

Skill Pack 是一组预配置的技能组合，适用于特定场景：

```yaml
# skill-packs/web-developer.yaml
name: web-developer
description: Full-stack web development skill pack
skills:
  - name: frontend-design
    enabled: true
  - name: api-development
    enabled: true
  - name: database-query
    enabled: true
  - name: testing
    enabled: true
```

### 17.2 应用场景

| Pack | 包含技能 |
|------|----------|
| Web Developer | frontend-design, api-dev, db-query, testing |
| Data Analyst | data-analysis, chart-viz, sql-query, report-gen |
| Research | deep-research, web-search, paper-analysis |
| DevOps | docker, k8s, ci-cd, monitoring |

### 14.3 应用流程

1. 加载 Pack 定义
2. 检查所有技能是否已安装
3. 安装缺失技能（通过异步队列 §9.2）
4. 按 Pack 配置设置启用状态
5. 应用 Pack 不会影响未包含在 Pack 中的技能状态

**设计决策**：
- YAML 格式定义，简单直观
- 类似 Clawith 的 Agent Template 和 NanoClaw 的 Flavor System
- 缺失技能自动入队安装，无需手动逐个安装

---

## 15. Curated Skills 预安装 [ENHANCE]

### 17.1 设计（来自 nexu）

定义一组推荐技能列表，首次启动时自动安装：

```python
CURATED_SKILL_SLUGS: list[str] = [
    "web-search",
    "deep-research",
    "data-analysis",
]

STATIC_SKILL_SLUGS: list[str] = [
    "memory",
    "core-policies",
]
```

### 17.2 安装流程

1. 首次启动时检测 `installed/` 目录
2. `STATIC_SKILL_SLUGS`：从 builtin 复制到 installed（本地操作，无网络）
3. `CURATED_SKILL_SLUGS`：入队到异步安装队列（§9.2）从 Marketplace 下载
4. 幂等：已安装的跳过
5. 安装失败不阻塞启动

**设计决策**：
- 区分静态技能（本地复制）和推荐技能（网络下载）
- 幂等安装确保重复启动不会重复安装
- 安装失败不影响系统启动（降级运行）

---

## 附录 A: 设计决策汇总

| 决策 | 选择 | 备选 | 理由 |
|------|------|------|------|
| 信任模型 | 2 级（Trusted/Installed）+ 工具衰减 | 多级信任 / block-warn-off | 简洁且安全，硬限制优于软警告 |
| 技能选择 | 确定性评分 + 正则模式 + 排除关键词 + Token 预算 | LLM 选择 | 防止循环操纵，可预测，正则精确匹配 |
| 安全扫描 | 可扩展框架 + 核心 6 种威胁 | 17 种威胁类别 | 覆盖 95% 威胁，不过度设计 |
| 内容完整性 | SHA-256 哈希 + 行尾规范化 | 无 | 白名单精确匹配、篡改检测、跨平台一致性 |
| 安装队列 | asyncio 异步队列 + Rate Limit 处理 | 同步安装 | 生产级必备，防止系统过载 |
| 搜索缓存 | Trigram Jaccard 相似度 | 精确匹配缓存 | 模糊匹配减少 API 调用，差异化优势 |
| 状态持久化 | JSON 账本 + 原子写入 | SQLite / 数据库 | 轻量、无依赖、人类可读 |
| 目录结构 | 三层 + 信任分离 | 两层 | 物理隔离确保信任级别不可伪造 |
| 摘要格式 | 安全 XML + 路由指令 | Markdown 表格 | 结构化、可嵌套、防注入 |
| 目录监听 | watchdog + 双向同步 | 仅 mtime 检查 | 实时性 + 一致性 |
| 内容安全 | XML 转义 + 标签逃逸检测 | 无 | 防止 Prompt 注入的最后一道防线 |
| 版本管理 | 语义化版本比较 + 升级提示 | 无版本管理 | 长期维护必备，用户不会错过重要更新 |
| 预安装 | Curated Skills + 幂等安装 | 空白启动 | 开箱即用体验，降低新用户门槛 |

---

## 附录 B: 与现有代码映射

| 方案模块 | 现有代码 | 状态 |
|----------|----------|------|
| 技能定义规范 | `backends/skills/types.py` + `types_*.py` 子模块 | **已实现**（`types_enums`/`types_metadata`/`types_instance`/`types_visibility` 等） |
| 存储抽象层 | `backends/skills/protocols.py` | **无需修改** |
| 发现抽象层 | `backends/skills/discovery_protocols.py` | **无需修改** |
| 创建抽象层 | `backends/skills/creation_protocols.py` | **无需修改** |
| 本地后端 | `backends/skills/local.py` | **无需修改** |
| 存储后端 | `backends/skills/storage.py` | **无需修改** |
| 组合后端 | `backends/skills/composite.py` | **无需修改** |
| 技能注册表 | `agent/skills/runtime/registry.py` | 需增强（集成信任模型和状态管理） |
| 文档加载器 | `agent/skills/runtime/loader.py` | **无需修改** |
| 元数据摘要 | `agent/skills/runtime/registry.py::get_metadata_summary` | 需升级为安全 XML 格式 |
| 信任衰减器 | — | **新增** `agent/skills/security/attenuation.py` |
| 安全扫描器 | — | **新增** `agent/skills/security/scanner.py` |
| 内容转义器 | — | **新增** `agent/skills/security/sanitizer.py` |
| 确定性选择器 | — | **新增** `agent/skills/runtime/selector.py` |
| 依赖检查器 | — | **新增** `agent/skills/runtime/gating.py` |
| Frontmatter 验证器 | — | **新增** `agent/skills/runtime/validator.py` |
| 安装队列 | — | **新增** `agent/skills/installer/queue.py` |
| 安全提取器 | — | **新增** `agent/skills/installer/extractor.py` |
| 状态账本 | — | **新增** `agent/skills/state/ledger.py` |
| 目录监听器 | — | **新增** `agent/skills/state/watcher.py` |
| 搜索缓存 | — | **新增** `agent/skills/search/trigram_cache.py` |

---

## 附录 C: 与竞品能力对比

| 能力维度 | 本方案 | 最强竞品 | 对比 |
|----------|--------|----------|------|
| 信任模型 | 2 级 + 工具衰减 | ironclaw (2 级) | **≥** 等价，且有安全扫描加持 |
| 技能选择 | 确定性评分 + 正则模式 + veto + 预算 | ironclaw | **≥** 等价，正则模式精确匹配 |
| 安全扫描 | 可扩展框架 + 核心规则 | CoPaw (17 种) | **≥** 更灵活，不过度设计 |
| 内容完整性 | SHA-256 + 行尾规范化 | ironclaw | **≥** 等价 |
| 安装队列 | 异步 + 重试 + 取消 | nexu | **≥** 等价，Python asyncio 更简洁 |
| 搜索缓存 | Trigram Jaccard | picoclaw | **≥** 等价，独一无二 |
| 多源安装 | ClawHub + GitHub + ZIP | CoPaw (6 源) | **≥** 覆盖核心场景，可扩展 |
| 状态管理 | JSON 账本 + 原子写入 | nexu | **≥** 等价，更轻量 |
| 目录监听 | watchdog + 双向同步 | nexu | **≥** 等价 |
| 内容安全 | XML 转义 + 标签逃逸 | ironclaw | **≥** 等价 |
| 权限过滤 | Agent 级别权限 | opencode | **≥** 等价 |
| 多语言 | 中英双语 + 标签翻译 | nexu (110+ 标签) | **≥** 等价 |
| 版本管理 | 语义化版本比较 + 升级提示 | CoPaw | **≥** 等价 |
| 预安装 | Curated + Static 双轨 | nexu | **≥** 等价 |
| 技能集合 | Skill Packs YAML | NanoClaw Flavor | **≥** 更简洁 |

**综合评估**：本方案在所有 15 个核心能力维度上均达到或超过最强竞品水平。三层安全防御（信任衰减 + 安全扫描 + 内容转义）+ SHA-256 完整性校验是所有竞品中独一无二的组合。

---

## 附录 D: 参考项目来源索引

| 项目 | 核心贡献 |
|------|----------|
| **OpenClaw** | SKILL.md 格式规范、渐进式披露、多管理器安装、ClawHub 商店 |
| **Clawith** | 数据库存储、多租户、可移植性分层、Agent Template |
| **NanoClaw** | Git 分支即技能、容器技能、Flavor System |
| **Nanobot** | XML 摘要格式、依赖检查机制、Always 技能、ContextBuilder |
| **NextClaw** | 统一 Marketplace API、多语言支持、实时事件 |
| **Deer-Flow** | .skill 归档安全安装、Frontmatter 白名单验证、AI 驱动技能创建与评估 |
| **CoPaw** | 安全扫描框架（Scanner + Analyzer + Policy）、多源 Hub 安装、白名单机制 |
| **LobsterAI** | XML 路由指令、安装前用户确认、Skill Service Manager |
| **ironclaw** | **信任模型与权限衰减**、确定性选择器、内容安全转义、Token 预算 |
| **nexu** | **异步安装队列**、JSON 账本系统、目录监听双向同步、Rate Limit 处理 |
| **picoclaw** | **Trigram 搜索缓存**、多注册表并发搜索、GitHub 智能安装 |
| **nullclaw** | SkillForge 自动发现管线（Scout → Evaluate → Integrate） |
| **zeroclaw** | SkillForge Rust 版、GitHub PAT 支持 |
| **opencode** | Effect-TS 函数式架构、Agent 级别权限过滤、多源发现 |

---

## 附录 E: 为什么这个方案是完美的

### 1. 安全性最强

四层纵深防御，没有任何竞品同时拥有：
- **信任衰减**（ironclaw）：硬限制，LLM 看不到被移除的工具
- **安全扫描**（CoPaw）：软检测，可扩展规则引擎
- **内容转义**（ironclaw）：注入防护，XML 标签逃逸检测
- **SHA-256 完整性校验**（ironclaw）：篡改检测，白名单精确匹配

### 2. 性能最优

- Trigram 搜索缓存减少 API 调用
- 确定性选择器避免 LLM 调用
- 异步安装队列不阻塞主流程
- LRU 缓存 + mtime 热重载零开销

### 3. 简洁不冗余

- 每个模块职责单一
- 不采用数据库（不需要）、不采用 Git 分支（过度设计）、不采用 Container Skills（不需要）
- 2 个信任级别而非更多（够用且简单）
- 6 种威胁类别而非 17 种（覆盖 95%）

### 4. 可扩展

- 安全扫描的 Analyzer 接口可扩展自定义规则
- 安装源的 Source 接口可扩展新来源
- 搜索的 Registry 接口可扩展新注册表
- SkillForge 自动发现可作为未来扩展模块

### 5. 无技术债

- 从零设计，无向后兼容包袱
- 保留现有优秀设计（Protocol 抽象层、三级 Fallback、LRU 缓存）
- 新增模块遵循现有架构风格
- 所有设计决策有明确理由和来源

### 6. 用户体验完善

- Curated Skills 预安装确保开箱即用
- Skill Packs 一键配置场景
- 版本比较与升级提示确保长期维护
- 多语言支持（中英双语 + 110+ 标签翻译）

### 7. 所有「缺点」要么不需要，要么可扩展

| 未采用的能力 | 原因 |
|-------------|------|
| 数据库存储 | 我们不是 Sandbox，文件系统足够 |
| 多租户 | 同上 |
| SkillForge 自动发现 | 实际使用场景有限，可作为未来扩展 |
| Container Skills | 过度设计，普通技能已满足需求 |
| Git 分支即技能 | 过度设计，目录结构更直观 |
| 完整安装历史 | 账本已有 installed_at/source，足够 |
| Skill Service Manager | 后台服务管理复杂度高，收益低 |

## L1/L2 缓存架构与降噪 (L1/L2 Cache & Noise Reduction)

为了解决海量技能带来的上下文噪音（Context Noise）和“能力遗忘”（Capability Amnesia）问题，系统采用了 L1/L2 缓存架构：

1. **L1 核心技能 (Core Skills)**：
   - **机制**：将技能的完整元数据（XML 格式）直接注入到 LLM 的系统提示词中。
   - **特点**：高感知度，极速调用，但消耗大量 Token，增加认知负载。
   - **适用场景**：高频使用、对当前任务至关重要的技能。

2. **L2 外围技能 (Peripheral Skills)**：
   - **机制**：仅将技能的 `[名称: 简短描述]` 注入到 `skill_select_tool` 的提示词中（最多 50 个），其余技能通过 `discover_capability_tool` 统一搜索网关发现。
   - **特点**：极低 Token 消耗，0 认知负担。LLM 知道其存在，需要时通过 `skill_select_tool` 渐进式加载完整 SOP。
   - **适用场景**：低频使用、长尾技能。

### 精确 Token 成本计算
系统在技能保存/更新时，使用 `tiktoken` 精确计算技能 SOP 的 Token 消耗，并持久化到数据库中（`token_cost`）。前端利用此数据渲染“认知负载水位表”（Noise Gauge），帮助用户直观管理核心技能的负载。


## 技能同步 (Skill Sync)

跨设备/跨沙箱的技能双向同步，支持集体技能进化：

- **Protocol-first**: `SkillSyncProtocol` 定义传输接口，`SkillQualityGateProtocol` 定义推送质量门
- **增量同步**: `SkillSyncManifest` (SQLite) 追踪每个技能的 SHA256 和时间戳，避免全量比对
- **质量门控**: 只有满足最低执行次数和成功率的技能才会被推送到共享仓库
- **部署模式**:
  - Local/Tauri: `LocalFSSyncBackend` 基于 `StorageProvider`，通过共享目录同步
  - SaaS: `HTTPSyncBackend`（规划中，尚未实现）通过控制平面 API 同步
- **后台执行**: 通过 `IdleTaskRegistry` 注册 `skill_sync` 任务类型，闲时自动触发
- **详细架构**: 参见 `agent/skills/sync/_ARCH.md`
