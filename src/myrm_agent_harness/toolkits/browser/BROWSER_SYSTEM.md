# 浏览器自动化系统设计

> 基于 Patchright (Chromium) 与 Camoufox (Firefox) 双引擎的 Agent 友好浏览器自动化方案

---

## 设计目标

1. **Agent 友好**：通过引用系统（@refs）和自愈定位器（O(1) BBox 特征）简化元素定位，消除因 DOM 变动导致的 Agent 崩溃，减少 Token 消耗。
2. **高性能**：混合会话降级机制（静态页极速 HTTP 注入）、零拷贝页面复用、MutationObserver变化检测、感知哈希截图对比。
3. **高安全**：URL scheme 白名单验证、四层纵深域名过滤（覆盖 Worker）、加密 Session 存储、审批机制与语义否决（Semantic Veto）。
4. **高可靠**：双引擎反爬机制（Patchright/Camoufox）、智能重试、精细化错误处理。

### 已登录站点与内网访问

产品**不读取**用户 OS 级 Chrome/Edge `History` 或 `Bookmarks` 数据库（无 Agent 工具、无 server 服务）。

| 场景 | 路径 | 层 |
|------|------|-----|
| 复用用户 Chrome 登录态（JIRA、内网等） | Agent 配置 `browser_source=extension` → Extension Bridge CDP 代理 | server `services/extension/` |
| 手动登录后跨会话保持 | `SessionVault` 加密保存 Cookies/Storage；`browser_manage` 保存/恢复 | harness `session/` + server `browser_vault` |
| Agent 跨引擎共享登录态 | SessionVault 注入 CrawlEngine / HttpFetcher | harness `navigation.py` |
| 找回「跟 Agent 聊过的 URL」 | `memory_recall_tool` / opt-in `conversation_search_tool` | harness memory + server adapter |

Extension Bridge 与 SessionVault 覆盖竞品（orca/holaboss）cookie 导入的核心收益，且无需读取 OS 浏览器数据库。

---

## 系统架构

### 整体架构图

```
┌─────────────────────────────────────────────────────────────┐
│                      LangChain Tools                        │
│  browser_navigate_tool | browser_snapshot_tool | browser_interact_tool    │
│  browser_extract_tool  | browser_manage_tool   | browser_execute_script_tool │
└──────────────────────────┬──────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│                    BrowserSession                           │
│  ┌──────────────┬──────────────┬──────────────┬──────────┐ │
│  │TabController │  Navigator   │SnapshotMgr   │Interactor│ │
│  │  Extractor   │CaptchaCoord? │              │          │ │
│  └──────────────┴──────────────┴──────────────┴──────────┘ │
└──────────────────────────┬──────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│                 GlobalBrowserPool                           │
│  ┌────────────────────────────────────────────────────┐    │
│  │  Context 1    Context 2    Context 3 (多租户隔离)  │    │
│  │    ├─ PagePool (零拷贝复用)                        │    │
│  │    ├─ PagePool                                     │    │
│  │    └─ PagePool                                     │    │
│  └────────────────────────────────────────────────────┘    │
└──────────────────────────┬──────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│                Dual-Engine Abstraction                      │
│  ┌────────────────────┐      ┌─────────────────────────┐    │
│  │ Patchright (Chromium)│      │ Camoufox (Firefox)      │    │
│  │ (Default, Fast)      │      │ (High Stealth, C++)     │    │
│  └────────────────────┘      └─────────────────────────┘    │
└─────────────────────────────────────────────────────────────┘
```

---

## 性能指标总览

| 维度 | 指标 |
|------|------|
| **页面重置** | ~50ms |
| **快照生成（微小变化）** | ~1ms |
| **快照生成（适中变化）** | ~10-20ms |
| **快照生成（大变化）** | ~20ms |
| **截图对比** | ~2ms |
| **Browser 启动鲁棒性** | 自动重试 3 次（指数退避） |

**架构质量指标**：

| 指标 | 状态 |
|------|------|
| SOLID 原则 | ✅ 100% 遵循 |
| 最大文件行数 | 716 行（GlobalBrowserPool） |
| 精细化错误处理 | ✅ 13 种异常类型 |
| 智能重试 | ✅ 3 种重试策略 |
| 生产就绪 | ✅ |

---

## 核心组件

### 1. GlobalBrowserPool - 全局资源池

**职责**：浏览器实例和页面对象的全局管理

**关键技术**：
- **零拷贝页面复用**：通过 CDP 命令快速重置页面（~50ms），避免关闭重建（~300ms）
- **Managed vs External 重置策略**（`PagePool.preserve_session`，由 `BrowserInstance.is_managed` 驱动）：
  - **Managed**（`LAUNCH` / AUTO fallback 新启 Chromium）：全量 CDP 清理（cookies、storage、cache）
  - **External**（CDP 连接用户 Chrome，`is_managed=False`）：仅 `Page.resetNavigationHistory` + 标签页 `about:blank`，**不**调用 `Network.clearBrowserCookies` / `Storage.clearDataForOrigin`，保留登录态
- **DevToolsActivePort 自动发现**：AUTO 模式通过 `chrome_discovery.py` 扫描 Chrome/Edge/Chromium/Brave/Canary 的 DevToolsActivePort 文件，自动发现用户本地浏览器的动态 CDP 端口。4 阶段策略：文件扫描 → HTTP probe（完整 CDP API）→ inspect WebSocket path + TCP（`chrome://inspect` 模式）→ 固定端口 9222 HTTP 兜底。
- **Local 可见 fallback**：server 层 `get_browser_launch_options()` 在 Local 模式设 `headless=False`（SaaS 仍默认 headless）
- **多租户隔离**：不同 ContextType（CRAWL / AGENT / STEALTH）使用独立 BrowserContext
- **智能负载调度**：自动选择负载最低的 Context
- **智能重试**：3次指数退避重试（2s/4s/8s），处理启动失败和网络异常
- **并发安全销毁**：支持 `destroy_context` 显式回收资源，并具备严格的并发安全断言，防止销毁正在使用的页面。
- **僵尸进程清理**：在底层浏览器卡死时，通过 `force_kill` (SIGKILL) 强制回收操作系统级别的进程资源。
- **双引擎热切换**：支持在 Chromium (Patchright) 和 Firefox (Camoufox) 之间无缝热切换，用于突破高强度反爬。
- **Camoufox 指纹持久化**：通过 `camoufox.utils.launch_options()` 生成完整指纹配置（含 `executable_path`、环境变量中的指纹种子、WebGL 参数等），首次启动时保存到 `_fingerprint_dir/camoufox_fingerprint.json`，后续启动通过 `from_options` 加载，确保同一 Agent 在多次会话中保持一致的设备身份。内置自愈机制：损坏的 JSON 配置文件（如断电导致写入中断）会被自动检测、删除并重新生成，避免永久启动失败。

**核心 API**：
```python
pool = GlobalBrowserPool(max_browsers=5)
await pool.warmup(browsers=2, pages_per_context=5)
page = await pool.acquire_page(ContextType.AGENT)
await pool.release_page(page, ContextType.AGENT)
```

---

### 2. BrowserSession - 会话管理器

**职责**：多 Tab 会话管理，组合各功能组件

**SOLID 设计**：
- **单一职责**：每个组件仅关注一个职责（Tab / 导航 / 快照 / 交互 / 提取）
- **组合优于继承**：BrowserSession 作为聚合根，薄层委托各组件
- **依赖注入**：可选注入 SessionVault 实现加密会话存储，用于在 BrowserFetcher 和 HttpFetcher 之间无缝共享登录态 (Cross-Engine Global Cookie Jar)。close() 时自动保存 auto_restore_domains 中有变化的域名会话（hash-diff 避免无效 I/O），并触发 SessionLifecycleHook 同步 agent 记忆。

**组件架构**：
```python
BrowserSession (聚合根)
├── TabController         # Tab 生命周期管理
├── Navigator             # 页面导航、历史控制
├── SnapshotManager       # ARIA 快照生成
├── Interactor            # 元素交互
├── Extractor             # 内容提取、截图、PDF
├── SessionVault?         # 加密会话存储（可选，用于跨引擎状态共享）
└── CaptchaCoordinator?   # CAPTCHA 检测与协调（可选，需注入 CaptchaSolver）
```

**核心能力**：
- 20+ 个公开方法覆盖导航、交互、提取、会话管理
- Tab 管理：LRU 驱逐策略（上限 10 个 Tab）+ Origin-based 智能路由（同源 URL 自动复用已有 Tab，避免重复创建）
- 会话管理：AES-256-GCM 加密，30 天 TTL 自动过期
- **无感自动降级/升级**：在导航遇到无法解决的 CAPTCHA (如 Cloudflare) 时，自动从 Chromium 热切换至 Camoufox 并重试，对 Agent 完全透明。通过精细的 `restore_url=False` 控制，避免切换引擎时产生双重导航（Double Navigation）的性能损耗和二次封杀风险。同时支持**状态无缝迁移 (Stateful Seamless Hot-Switching)**，在引擎切换或代理轮换瞬间，自动提取并重新注入 Cookie 和 `localStorage`，确保登录态和会话上下文 100% 不丢失。
- **代理智能轮换与防封自愈**：在底层集成 `is_proxy_error` 与 `is_blocked_response` 检测。遇阻瞬间触发：隔离坏代理至小黑屋 -> `restart()` 无损热替换上下文获取新 IP -> 重新导航。全程对 LLM 透明，0 额外 Token 成本。

---

### 3. FrameRegistry & FrameState - 增量快照管理

**职责**：为每个 Frame 提供独立的增量快照能力，支持 iframe 穿透

**架构设计**：
- **FrameState**：管理单个 Frame 的 MutationObserver 和 ARIA 树缓存
- **FrameRegistry**：聚合多个 FrameState，处理 iframe refs 前缀（f1_e0, f2_e1）

**核心算法**：
```python
async def capture():
    changes = await detect_changes()  # MutationObserver（每个 Frame 独立）
    
    if len(changes) < 5:
        return cached_snapshot  # ~1ms，缓存命中
    elif len(changes) < 50:
        return await full_snapshot()  # ~10-20ms
    else:
        return await full_snapshot()  # ~20ms
```

**性能优化机制**：
- MutationObserver缓存：无变化时直接返回缓存，跳过ARIA树抓取
- 多 Frame 并行处理：主框架和 iframe 并行捕获快照
- CDP 快速重置：PagePool使用CDP命令重置页面状态
- 感知哈希（dHash）：快速截图对比，零外部依赖

---

### 4. 截图对比系统 - 双重实现

**职责**：提供快速和精确两种截图对比策略

#### 4.1 FastComparator - 快速对比（dHash）

**核心技术**：dHash（Difference Hash）
**性能**：~2ms
**适用场景**：快速检测视觉变化、动画/加载完成检测

```python
def dhash(image, hash_size=8):
    # 1. 灰度化 + 缩放到 9x8
    gray = image.convert('L').resize((hash_size + 1, hash_size))
    # 2. 计算水平梯度（相邻像素差值）
    # 3. 生成 64-bit 哈希
    # 4. 汉明距离计算相似度
    similarity = 1 - (hamming_distance / 64)
```

#### 4.2 AccurateComparator - 精确对比（Canvas API）

**核心技术**：浏览器 Canvas getImageData API
**性能**：~100ms
**适用场景**：调试视觉回归、定位像素级变化

**特性**：
- 隔离页面架构（避免 CSP 干扰）
- Route 拦截（避免 CDP 消息大小限制）
- 红色标记 diff 图生成
- 颜色距离容差（支持抗锯齿）

#### 4.3 LLM 友好性设计

**统一类型系统**：
```python
class ComparisonResult(Protocol):
    @property
    def similarity(self) -> float: ...
    @property
    def is_significant_change(self) -> bool: ...
    @property
    def algorithm(self) -> str: ...
    def to_llm_message(self) -> str: ...
```

**设计理念**：
- **语义清晰**：`strategy='fast'` vs `'accurate'`（而非数字参数）
- **字符串输出**：`to_llm_message()` 返回自然语言描述（而非 JSON）
- **智能判断**：`is_significant_change` 属性自动判断是否需要关注
- **算法透明**：输出中包含算法名称（`dHash` / `Canvas API`）

**使用示例**：
```python
# 方式1：通过工具（LLM 直接调用）
result = await browser_extract_tool(mode="diff_fast", baseline=last_screenshot)
# 输出：
# "✅ SIMILAR (similarity: 0.98, hamming distance: 1/64)
#  Algorithm: dHash (fast perceptual hash)"

result = await browser_extract_tool(mode="diff_accurate", baseline=last_screenshot)
# 输出：
# "❌ CHANGE DETECTED (similarity: 0.85, mismatch: 15.0%)
#  Different pixels: 15000/100000
#  Algorithm: Canvas API + YIQ color space (perceptual comparison)
#  Anti-aliasing detection: Enabled
#  Diff image available (base64, red=difference, yellow=anti-aliasing)"

# 方式2：通过 Python API（内部使用）
from myrm_agent_harness.toolkits.browser import BrowserSession

result = await session.compare_screenshots(baseline, strategy="fast")
# FastComparisonResult(similarity=0.98, hamming_distance=1, ...)

result = await session.compare_screenshots(baseline, strategy="accurate")
# AccurateComparisonResult(similarity=0.85, mismatch_percentage=15.0, diff_image_b64="...", ...)
```

**核心优势**：
- LLM 无需理解复杂参数组合（如 `threshold` 的含义）
- 输出格式友好，直接可理解（SIMILAR / CHANGE DETECTED）
- 算法名称明确，便于 LLM 决策何时使用
- Protocol 设计保证开发者类型安全

---

### 5. ARIA Snapshot - 引用系统

**设计目标**：让 Agent 通过简单的 ref ID（如 `e0`, `e1`）定位元素，而非复杂的 CSS 选择器

**架构流程**：

```
page.locator(':root').aria_snapshot()
  ↓ Playwright 返回 YAML 字符串
parse_and_enhance_aria_tree(aria_tree, scope="interactive", compact=False)
  ↓ 正则解析，根据 scope 识别元素
  ↓ 注入 ref ID（e0, e1, f1_e0, ...）
  ↓ 处理 nth 消歧
  ↓ 生成 metadata（ref_count, estimated_tokens）
(enhanced_text, refs: dict[str, RefInfo], metadata: SnapshotMeta)
```

**输入示例**（Playwright YAML）：
```yaml
- button "Submit"
- textbox "Email"
- link "Home"
```

**输出示例**（增强后）：
```yaml
- button "Submit" [ref=e0]
- textbox "Email" [ref=e1]
- link "Home" [ref=e2]
```

**iframe 穿透**：
- 主框架：`e0`, `e1`, `e2`, ...
- iframe 1：`f1_e0`, `f1_e1`, ...
- iframe 2：`f2_e0`, `f2_e1`, ...

**三层角色分类**：
- **INTERACTIVE**（17 种）：button, link, textbox, checkbox, ...
- **CONTENT**（10 种）：heading, cell, listitem, article, ...
- **STRUCTURAL**（18 种）：generic, group, list, table, ...

通过 `scope` 参数控制可见性和 ref 分配：
- `scope=interactive`（默认）：仅交互元素获得 ref
- `scope=content`：交互 + 内容元素获得 ref
- `scope=full`：所有元素获得 ref

---

### 6. 语义感知 Diff

**问题**：标准文本 diff 在 ARIA 快照上失效，因为 ref ID 每次重新编号

**解决方案**：Ref-ID 归一化

```python
# 归一化：移除 ref ID
"e0 [link] 'Home'"  →  "[link] 'Home'"
"e1 [link] 'Home'"  →  "[link] 'Home'"

# diff 算法在归一化文本上运行
difflib.SequenceMatcher(prev_normalized, curr_normalized)

# 输出使用原始文本（含 ref ID）
```

**Equal 段折叠**：长 unchanged 段（>3 行）折叠为摘要

**三段式交互元素追踪**：
```
--- New interactive: e0 (banner "Ad") ---
--- Removed interactive: (button "Delete") ---
--- Unchanged interactive: e1, e2, e3 ---
```

---

### 7. Cursor-interactive 检测与 Shadow DOM 穿透

**问题**：许多网页使用 `<div onclick>` / `cursor:pointer` 实现可交互元素，标准 ARIA 树无法捕获。同时，现代 Web Components 将真实 DOM 封装在 Shadow DOM 内，导致原生 `querySelectorAll` 彻底失效。

**解决方案**：底层无盲区 JS 探针探测
1. 我们手写了高度优化的 JS 收集脚本 (`observer_scripts.py`)，**原生实现了全量 `shadowRoot` 的递归穿透遍历**。无论是 `BBOX_COLLECTOR_SCRIPT` 还是 `MUTATION_OBSERVER_SCRIPT`，均保证 100% 不遗漏任何封装在 Web Components 内部的组件坐标与状态变动。`Extractor.extract_full_text()` 的 `nodeToMarkdown` 同样实现了 `shadowRoot` 递归穿透，确保文本提取完整性。
2. JS 引擎通过 `window.getComputedStyle(el).cursor === 'pointer'` 或检测 `onclick`/`tabIndex` 来兜底拾取那些不规范的交互元素，赋予其 `role="clickable"`。

```javascript
// 阶段 1：显式信号
document.querySelectorAll('[onclick],[tabindex],[data-click]')

// 阶段 2：cursor:pointer
document.querySelectorAll('div,span,li,td')
  .filter(el => {
    const style = window.getComputedStyle(el);
    return style.cursor === 'pointer' && !hasInteractiveChild(el);
  })
```

**输出融合**：使用虚拟 role（`clickable` / `focusable`），统一分配 ref ID

---

### 8. Session Vault - 加密会话存储

**设计目标**：跨会话登录态保持，支持手动登录后保存状态

**加密方案**：
```
AES-256-GCM (AEAD)
  密钥: 256-bit 随机生成，0600 权限存储
  格式: nonce(12) || ciphertext || tag(16)
  明文: JSON(SessionEntry) — cookies + localStorage + 元数据
```

**域名隔离**：
- Cookie domain 匹配（支持 leading dot：`.github.com` → `github.com` 及子域名）
- localStorage 按 origin 过滤

**TTL 自动过期**：
- 默认 30 天 TTL（可配置）
- `load()` 时自动检查过期，即时删除

**跨引擎状态共享 (Cross-Engine Global Cookie Jar)**：
- SessionVault 实例被注入到 `CrawlEngine` 及其底层的 `HttpFetcher` 和 `BrowserFetcher` 中。
- 当 Agent 使用 `browser_navigate_tool` 登录并保存状态后，`web_fetch_tool` (使用 `HttpFetcher`) 可以自动从 SessionVault 中读取对应域名的 Cookies 并注入到请求中，实现无缝的跨引擎状态共享，极大提升了认证页面的抓取效率。

**可插拔后端**：
```python
class SessionVaultBackend(Protocol):
    async def read(self, domain: str) -> bytes | None: ...
    async def write(self, domain: str, data: bytes) -> None: ...
    async def delete(self, domain: str) -> bool: ...
    async def list_all(self) -> list[str]: ...
    async def backup_corrupted(self, domain: str, data: bytes) -> None: ...
```

- **FileVaultBackend**：本地文件系统，使用 URL 编码文件名防止域名冲突
- **DbVaultBackend**：数据库存储（预留接口，零代码改动即可切换）

**Session–Memory Bridge（Agent 跨会话身份记忆）**：

当 Agent 保存/删除浏览器登录态时，`SessionMemoryBridge` 自动维护一个 `active_browser_sessions` Profile 属性。该属性由 `memory_context_middleware` 自动注入到每轮 LLM 上下文的 `<user_memory_context> / Global User Profile` 区域，使 Agent **零额外工具调用**即可感知所有可用登录态。

```
用户："帮我发一条推文"
Agent 上下文已包含: active_browser_sessions: twitter.com (Jun 08), github.com (Jun 05)
Agent 直接调用: restore_session("twitter.com") → 节省 1 次 LLM 推理
```

- **Protocol 驱动**：`SessionLifecycleHookProtocol` → `on_session_saved / deleted / expired`
- **Fire-and-forget**：异步触发，不阻塞 save/delete 操作本身
- **容量控制**：最多追踪 10 个最近使用的 session，避免 Profile 膨胀
- **Prompt Cache 安全**：Profile 属性仅在 session 增删时变更（极低频），不影响缓存命中率

---

### 9. URL Scheme 白名单验证

**设计目标**：在导航层面阻断危险 URL scheme，防止 XSS、本地文件访问、数据注入等攻击

**实现位置**：`Navigator._validate_url_scheme()`

**白名单机制**：
```python
_ALLOWED_SCHEMES = frozenset(["http", "https", "about"])
```

**允许的 scheme**：
- `http://` / `https://`：标准 Web 协议
- `about:`：浏览器内置页面（如 `about:blank`）

**拒绝的危险 scheme**：
- `javascript:`：XSS 攻击向量（可执行任意脚本）
- `file:`：本地文件系统访问（如 `file:///etc/passwd`）
- `data:`：内联数据注入（如 `data:text/html,<script>alert(1)</script>`）
- `blob:`：Blob URL 注入
- `ftp:`：非 HTTP 协议

**错误信息示例**：
```
ValueError: Blocked URL scheme: 'javascript' not allowed (only http/https/about permitted).
Rejected dangerous schemes: javascript/file/data/blob/ftp. Got: javascript:alert(1)
```

**测试覆盖**：16 个测试，覆盖允许/拒绝场景、边界情况（缺少 scheme、相对 URL、大小写不敏感）

---

### 10. 四层纵深域名过滤

**设计目标**：覆盖主线程和 Web Worker 的所有网络出口通道，防止数据泄露

```
Layer 0: CSP (Content-Security-Policy)   ← BROWSER KERNEL (主线程 + Worker)
Layer 1: context.route('**/*')           ← PROTOCOL BLOCK (HTTP/HTTPS)
Layer 2: addInitScript() + defineProperty ← MAIN THREAD HARD (WebRTC/SW)
Layer 3: CDP Network.webSocketCreated     ← AUDIT VISIBILITY
```

**Layer 0（CSP）指令**：
- `connect-src`: 限制网络连接（fetch/XHR/WebSocket/EventSource/sendBeacon）
- `script-src`: 限制脚本加载（允许 inline/eval 以兼容现代框架）
- `frame-src`: 限制 iframe 加载
- `object-src 'none'`: 禁用插件（Flash/Java）
- **不限制** img-src/style-src/font-src/media-src（允许 CDN 资源加载）

**Layer 0（CSP）核心优势**：
- 浏览器内核层执行（W3C 标准原生实现）
- 自动覆盖主线程和所有 Web Worker（包括 WebSocket/EventSource/sendBeacon）
- 成熟可靠，无法被页面脚本篡改

**Layer 2 硬化机制**：

```javascript
Object.defineProperty(window, 'RTCPeerConnection', {
  value: BlockedConstructor,
  writable: false,
  configurable: false
});
```

**覆盖通道**：
- Layer 0（CSP）: **主线程 + Worker**: fetch/XHR/WebSocket/EventSource/sendBeacon/importScripts
- Layer 1: HTTP/HTTPS
- Layer 2: RTCPeerConnection, WebTransport, Service Worker registration
- Layer 3: WebSocket audit（含 Worker）

**反爬检测友好**：保留 Web Worker 功能（避免 `new Worker()` 抛异常），与 browser-use（81K stars）策略一致

---

### 11. 三层反检测体系与拟人化交互

**第一层：Patchright CDP 泄露修补**

| 检测点 | 标准 Playwright | Patchright 修补 |
|-------|----------------|----------------|
| `Runtime.enable` | ✅ 泄露 | ❌ 避免（用 ExecutionContext） |
| `Console.enable` | ✅ 泄露 | ❌ 禁用 |
| `--enable-automation` | ✅ 泄露 | ❌ 添加 `--disable-blink-features=AutomationControlled` |
| `navigator.webdriver` | ✅ 泄露 | ❌ 注入脚本隐藏 |

**第二层：JS 反检测脚本（仅 STEALTH ContextType，通过 `add_init_script()` 一次注入）**

| # | 措施 | 说明 |
|---|------|------|
| 1 | navigator.webdriver → false | 双重保险（与 patchright 互补） |
| 2 | window.chrome stub | headless 环境 chrome 对象缺失修复 |
| 3 | navigator.plugins 伪造 | headless 环境 plugins 为空修复 |
| 4 | navigator.languages 保证 | 自动化环境空数组修复 |
| 5 | Permissions.query 修复 | headless 对 notifications 抛异常修复 |
| 6 | 自动化工件清理 | 清除 __playwright/__puppeteer/cdc_ 全局变量 |
| 7 | CDP stack trace 清理 | 过滤 Error.stack 中的自动化脚本 URL |
| 8 | WeakMap+toString 伪装 | 核心反爬手段：使 patched 函数的 toString() 返回 native 字符串 |
| 9 | Anti-debugger 中和 | 中和 Function/eval 中的 debugger 语句 + CDP Debugger.setBreakpointsActive(false) |
| 10 | Console 方法指纹伪装 | 修复 CDP 替换 console 方法后的 toString 不一致 |
| 11 | outerWidth/Height 防护 | DevTools 尺寸差异检测防护 |
| 12 | Performance API 清理 | 过滤 CDP 注入的 timing entries |
| 13 | Iframe chrome 一致性 | iframe 中 chrome 对象缺失修复 |

**第三层：拟人化交互隐身 (Humanized Interaction Stealth)**
**设计目标**：规避 WAF 针对机器级精准点击和超高速打字的检测。
**实现机制**：
- **打字延迟**：在 `type` 动作中引入随机的按键延迟（30-100ms/char），模拟人类输入节奏。
- **点击延迟**：在 `click` 和 `dblclick` 动作中引入随机的按下/抬起延迟（50-150ms），模拟真实鼠标点击。
- **动态超时自适应**：根据文本长度和随机延迟动态计算 `timeout`，防止因拟人化延迟导致 Playwright 内部超时崩溃。

**反检测验证**（内部基准，非全站保证；高强度站点可能仍需自动升级到 Camoufox）：

| 检测系统 | 标准 Playwright | Patchright（默认） | Camoufox（自动升级） |
|---------|----------------|-------------------|---------------------|
| BrowserScan | ❌ 检测到 | ✅ 多数通过 | ✅ 更强指纹伪装 |
| Fingerprint.com | ❌ 检测到 | ✅ 多数通过 | ✅ Firefox 指纹池 |
| CreepJS | ❌ 100% headless | ✅ 显著改善 | ✅ 非 headless 信号 |
| Cloudflare | ❌ 常拦截 | ⚠️ 部分通过 | ✅ 自动升级目标 |
| DataDome | ❌ 常拦截 | ⚠️ 部分通过 | ✅ 自动升级目标 |

**用户配置面（三轴，零引擎选择）**：
- 用户仅启用 Browser 内置工具，并在 Agent 编辑页配置：**browser_source**（启动/连接方式）、**dialog_policy**（JS 弹窗策略）、**session_recording**（录制策略）
- **browser_engine 不是用户配置项**：Server 传 `engine_preference=None`，引擎由框架内 Stealth Ladder 自动决定

**Stealth Ladder 触发条件**：
1. 默认 Patchright 导航
2. HTTP 403/429：代理重试耗尽后 fallthrough 至 CAPTCHA 检测（页面已加载）
3. CAPTCHA/反爬检测失败 → 自动升级 Camoufox + Progress SSE（`notify_category=browser`）
4. 仍失败 → Terminal Challenge（10min TTL，0ms 快速失败，防 LLM 反复重试）

**生产验证域名**：
- 微信公众号 (mp.weixin.qq.com)
- 微博 (weibo.com)
- 知乎 (zhihu.com)
- 小红书 (xiaohongshu.com)
- 抖音 (douyin.com)
- Twitter / X / Instagram / Facebook

---

### 12. 渐进式 Web 增强器与 SPA 稳态检测

**设计目标**：彻底解决 Agent 面临现代复杂框架（React/Vue）及单页应用（SPA）时的“交互失明”与“时序灾难”。

**第一层：渐进式交互增强器 (Progressive DomEnhancer)**
- **React 嗅探**：极速侦测并劫持 Fiber 树，提取带有真实意图（`onClick`等）的交互节点。
- **CDP 底层嗅探（兜底机制）**：无视前端框架，通过 Chrome DevTools Protocol 直接读取全局的事件监听器，100% 暴露出所有隐藏的无语义 `div` 按钮。
- **免侵入提取**：动态附加 `data-myrm-react-interactive` 和 `role=button` 属性，让 Playwright ARIA 快照原生接管。

**第二层：智能 SPA 混合观测器 (Smart SPA WaitStrategy)**
- **路由级**：拦截 `history.pushState` 捕获虚拟导航。
- **网络级（智能降噪）**：自动过滤心跳、埋点分析和 WebSocket 长连接，仅统计有价值的 Fetch/XHR 数据请求 (In-flight requests == 0)。
- **渲染级**：500ms MutationObserver 渲染防抖。
**首选应用场景**：集成于 `WaitStrategy.SPA_STABLE`，作为所有交互动作（`click`, `type`等）之后的默认检测原语，消灭长连接导致的超时死锁。

---

## 工具设计

### 8 工具 → 35+ 能力映射

压缩 Playwright MCP 的 24+ 个独立工具为 8 个语义分组工具，通过 `action` 参数扩展：

| 工具 | 覆盖能力 | action 参数 |
|------|---------|------------|
| `browser_navigate_tool` | 导航 | _(单一职责，无 action)_ |
| `browser_inspect_tool` | **轻量级页面结构分析** | _(单一职责，无 action)_ |
| `browser_snapshot_tool` | ARIA 快照 + iframe + Token 优化 + cursor-interactive | `scope`, `compact`, `selector`, `max_tokens`, `diff`, `cursor_interactive` |
| `browser_interact_tool` | 13 种交互 | click, dblclick, type, fill, press, hover, focus, select, scroll, upload_file, drag, check, uncheck |
| `browser_extract_tool` | 文本 + 截图 + 媒体URL + 结构化提取 + diff | text / screenshot / media / diff_fast / diff_accurate + extraction_schema |
| `browser_manage_tool` | Tab + JS + 历史 + 对话框 + Session + Network + HITL | 21 种 action（含 network_detail/network_replay + save/restore/list/delete_session + wait_for_user） |
| `browser_execute_script_tool` | **Code-as-Action 批量执行** + AST 特权API门禁 | _(执行 Python 脚本，AST 扫描 page.request/evaluate/context 等特权API → HITL 审批)_ |
| `browser_ask_human_tool` | **人类接管请求** | _(单一职责，Agent 触发 HITL interrupt + VNC 自动弹出)_ |

**Token 成本**：~65 tokens（相比独立工具方案节省 86%）

#### 两阶段快照架构

`browser_inspect_tool` + `browser_snapshot_tool` 实现信息分层：

**阶段 1**：轻量级探索（browser_inspect_tool）
- 返回：页面结构 metadata（~100 tokens）
- 性能：~15ms
- 用途：了解页面结构，获取精准 selector 推荐

**阶段 2**：精准捕获（browser_snapshot_tool）
- 返回：优化后的 ARIA 树（~1200 tokens）
- 性能：~100ms
- 用途：基于 inspect 的建议，捕获目标区域

**收益**：首次调用成本从 8000 tokens → 100 tokens（-99%），总成本从 9200 → 1300（-86%）

#### API-First 网络智能（NetworkIntelligence）

基于 CDP（Chrome DevTools Protocol）的懒加载网络响应体检索，赋予 Agent "API-First" 数据提取策略：

**核心能力**：
- **自动发现 API**：通过 `network_log` action 查看 XHR/Fetch 请求列表，含 POST body 预览（前 200 字符，便于区分 GraphQL operationName）
- **懒加载响应体**：通过 `network_detail` action 按需获取指定请求的完整响应体（最大 8000 字符），无内存浪费
- **请求重放**：通过 `network_replay` action 在页面上下文中重放 API 请求获取最新数据

**典型场景**：
- GraphQL 应用：通过 POST body 区分不同 operation，直接获取结构化 JSON
- Canvas/图表渲染：底层数据通过 API 传输，无法从 DOM 提取
- SPA 数据密集应用：API 响应包含完整数据，避免繁琐的 DOM 遍历

**零开销设计**：CDP 事件监听只存储请求元数据（requestId），响应体仅在 Agent 主动请求时通过 `Network.getResponseBody` 延迟获取。

---

## Token 优化策略

### Token 优化策略

| 策略 | 参数/工具 | 效果 | 典型节省 |
|------|----------|------|---------|
| **两阶段快照** | `browser_inspect_tool` + `browser_snapshot_tool` | 先探索再精准捕获 | 大幅减少 |
| **Selector 作用域** | `selector=".main"` | 限定快照范围 | 显著减少 |
| **Scope 控制** | `scope="interactive"` | 只显示交互元素 | 大幅减少 |
| **Compact 格式** | `compact=True` | 去缩进，单行格式 | ~20% |
| **Diff 模式** | `diff=True`（默认） | 仅返回变化 | 大幅减少 |
| **Token 截断** | `max_tokens=N` | 超出截断 | 精确控制 |
| **截图压缩** | JPEG q=50, 1280x720 | 降低质量 | 减少体积 |

**推荐工作流**（未知页面）：
1. `browser_inspect_tool()` → 获取结构 metadata（~100 tokens）
2. 查看推荐 → 决策最优参数
3. `browser_snapshot_tool(optimized_params)` → 获取目标快照

**参数优先级**: `selector` > `scope` > `max_tokens`（优先使用结构化优化，最后才用线性截断）

### 元信息自述

每次 snapshot 输出自带量化头部：

```
[42 refs | ~180 tokens | title: "Login" | url: example.com/login]
```

Agent 根据元信息自主决定优化策略，无需隐式知识。

---

## 安全架构

### 动态权限解析

```
browser_interact_tool(action="click")          → browser_click     → ALLOW (+ Semantic DOM Guard)
browser_interact_tool(action="fill")           → browser_fill      → ASK
browser_interact_tool(action="upload_file")    → browser_upload    → ASK
browser_manage_tool(action="evaluate")         → browser_evaluate  → DENY (L1 ToolApproval; L2 Semantic JS Guard on mutating expressions that reach session evaluate)
browser_manage_tool(action="save_session")     → browser_session   → ASK
browser_manage_tool(action="wait_for_user")    → browser_human_handover → ASK (handover 模式)
```

### 语义级 DOM 高危动作拦截 (Semantic DOM Guard)

在 **BrowserSession.interact**（覆盖 `browser_interact_tool` 与 `browser_execute_script` 内 `session.interact()`）的 click/dblclick 执行前，基于目标元素的 ARIA role 和 name 进行语义风险分类。匹配五大高危类别（destructive/financial/account/admin/publish）时，通过 LangGraph `interrupt()` 强制触发 HITL 审批，无论当前权限配置如何。`browser_execute_script_tool` 执行期间通过 `BrowserSession._hitl_caller_tool` 将 HITL/audit 的 `tool_name` 归因到脚本入口（`finally` 复位）。

**browser_manage evaluate**：L1 默认 `browser_evaluate` → DENY（`core/security/types.py`）；经 YOLO/allowlist 放行后，L2 变异 JS（`.click()`、`submit()`、`innerHTML=` 等）经 `classify_js_eval_risk` 仍走 HITL；只读表达式（如 `document.title`）直接执行。WebUI `high_risk_dom_action` 审批卡展示 `tool_input.expression`（zh/en `jsExpression`）。

```
click(ref="e5", name="Delete Repository") → HIGH (destructive) → interrupt() → 用户审批
click(ref="e3", name="Pay Now")           → HIGH (financial)   → interrupt() → 用户审批
click(ref="e1", name="Search")            → SAFE               → 直接执行
evaluate("document.querySelector('.pay').click()") → HIGH → interrupt()
evaluate("document.title")                → SAFE               → 直接执行
```

实现：`tools/_semantic_risk.py`（纯函数）+ `tools/semantic_dom_hitl.py`（共享 interrupt 路径）

### URL 安全验证

**Scheme 白名单验证**（第一道防线）：
```
navigate(url="http://example.com")      → ALLOW (http/https/about)
navigate(url="javascript:alert(1)")     → DENY (危险 scheme)
navigate(url="file:///etc/passwd")      → DENY (本地文件访问)
navigate(url="data:text/html,<script>") → DENY (数据注入)
```

**域名/IP 解析**（第二道防线）：
```
navigate(url="https://example.com")  → ALLOW
navigate(url="192.168.1.1")          → DENY (Sandbox) / ALLOW (Local)
navigate(url="localhost:3000")       → DENY (Sandbox) / ALLOW (Local)
```

### 信任边界标记

浏览器工具返回的所有外部内容（snapshot, extract_text）通过 `wrap_with_external_sources_tag(content, source="browser")` 包装，提供 5 层安全防护：

```
[SECURITY NOTICE: UNTRUSTED external content below...]
<<<UNTRUSTED_DATA id="random_boundary_id">>>
Source: browser
---
[actual ARIA tree / page text]
<<<END_UNTRUSTED_DATA id="random_boundary_id">>>
```

防御 indirect prompt injection，包含：
- L1: Unicode Folding（26种角括号规范化）
- L2: 不可见字符过滤（13类）
- L3: 可疑模式检测（20种）
- L4: 随机边界 ID
- L5: 安全提示前缀（指示 LLM 不执行内容中的指令）

---

## 错误处理

### 异常类型层次

```
BrowserError (root)
├── BrowserPoolError
│   ├── BrowserLaunchError
│   ├── BrowserShutdownError
│   └── BrowserPoolExhaustedError
├── BrowserSessionError
│   ├── BrowserNavigationError
│   ├── BrowserTimeoutError
│   ├── BrowserNetworkError
│   └── BrowserClosedError
└── BrowserToolError
    ├── ToolExecutionError
    └── ToolConfigurationError
```

### 重试策略

- `NavigationRetryPolicy`：3次，指数退避 1s/2s/4s
- `LaunchRetryPolicy`：2次，固定 2s
- `NetworkRetryPolicy`：5次，指数退避 1s/2s/4s/8s/16s

---

### 13. CAPTCHA 检测与协调

**设计目标**：在浏览器自动化场景中，检测阻塞性 CAPTCHA 并协调 Agent 暂停/恢复。

**架构设计**：

```
BrowserSession.navigate() / BrowserSession.interact(click/dblclick)
  ↓ Navigator.goto() / Interactor.interact()
  ↓ _handle_captcha_if_detected()
  ↓   detect_captcha(page) — HTML 正则匹配
  ↓   [if blocking CAPTCHA detected]
  ↓   CaptchaCoordinator.handle_captcha()
  ↓     → publish CAPTCHA_DETECTED event
  ↓     → CaptchaSolver.solve() (asyncio.wait_for + timeout)
  ↓     → publish CAPTCHA_RESOLVED / CAPTCHA_TIMEOUT event
  ↓   [resume flow]
```

**检测机制**（两层）：
- **Tier 1（高置信度）**：任意页面大小均触发，匹配 Cloudflare Challenge、Turnstile、PerimeterX、DataDome、Kasada、Akamai、Imperva
- **Tier 2（短页面）**：仅页面 < 10KB 时触发，匹配 "Checking your browser"、reCAPTCHA/hCaptcha（短页面上意味着是拦截页而非嵌入式组件）

**可插拔求解器**（Protocol 模式）：
```python
class CaptchaSolver(Protocol):
    async def solve(self, captcha_info: CaptchaInfo, page: Page) -> CaptchaSolveResult: ...
```

- **ManualSolver**（默认）：轮询页面检测 CAPTCHA 消失，支持 Local/Tauri/SaaS 部署
- 第三方求解器（2captcha、CapSolver 等）可无依赖实现此 Protocol

**状态机**：`NONE → DETECTED → SOLVING → RESOLVED | TIMEOUT`

**无感自动降级/升级**：
如果检测到高强度拦截（如 Cloudflare）且 `CaptchaCoordinator` 返回 `TIMEOUT` 或无法解决，且当前引擎为 `Chromium`，`BrowserSession.navigate` 会自动在底层触发 `restart(engine=CAMOUFOX, restore_url=False)`，热切换至深度隐身引擎并重新发起单次导航，成功后将结果返回给 Agent。这一过程对大模型完全透明，节省了大量推理 Token，且彻底规避了引擎切换过程中的双重导航（Double Navigation）死角。

**终端挑战硬停机 (Terminal Challenge Hard-Halt)**：

当 CAPTCHA 检测 + CAMOUFOX 自动升级 + 人类接管（HITL）均失败后，`navigate()` 通过 `ToolError` 结构化异常明确通知 Agent：

```
ToolError(
  error_code="BROWSER_TERMINAL_CHALLENGE",
  message="[TERMINAL_CHALLENGE] Navigation to example.com blocked by unsolvable cloudflare verification challenge.",
  user_hint="Do NOT retry navigation to this domain — it will fail again. Report this to the user and suggest alternatives."
)
```

**终端挑战记忆 (Terminal Challenge Memory)**：
- 首次失败后，域名被记录到 `BrowserSession._terminal_challenges` 内存字典。
- 后续导航同一域名时，0ms 快速失败（跳过 240s 的检测+求解+升级超时），返回 `BROWSER_TERMINAL_CHALLENGE_CACHED` ToolError。
- TTL 10 分钟，过期后自动清除，允许 re-attempt（网站可能已移除验证）。
- 轻量实现：无 LRU 库依赖，纯 `dict[str, float]`，单 session 生命周期内域名数有限，无内存泄漏风险。

**设计优势**：
- 与 `LoopGuard`（agent/security/guards/loop_guard.py）协同：LoopGuard 限制总重试次数，Terminal Challenge Memory 将每次重试的时间成本从 240s 降至 0ms。
- `CaptchaHandleResult` 结构化返回（protocols.py）提供类型安全的 CAPTCHA 处理结果判断。

**前端集成**：通过 `CAPTCHA_DETECTED / CAPTCHA_RESOLVED / CAPTCHA_TIMEOUT` 三种 SSE 事件，前端渲染为 ProgressItem 状态卡片。

---

### 14. Code-as-Action 脚本执行引擎

**设计目标**：打破单步工具调用的性能瓶颈（网络延迟、LLM 推理延迟），允许 Agent 生成并执行包含多个动作的 Python 脚本。

**架构设计**：
- **AST 动态重写**：自动拦截 `while` 和 `for` 循环，注入 `await asyncio.sleep(0)`，彻底防止死循环阻塞主事件循环。
- **沙箱隔离**：使用受限的 `__builtins__`（移除 `__import__`, `eval`, `exec`, `open`, `exit` 等），确保脚本无法逃逸或破坏主进程。
- **流式输出**：重写 `print` 函数，将脚本的输出通过 `session.notify_progress` 实时推送到前端控制台。
- **ARIA 映射**：脚本中可以直接使用 `await session.interact("click", "e1")`，底层自动解析 `e1` 对应的 Playwright Locator。

**核心优势**：
- **零延迟**：脚本在主进程的协程中运行，直接访问内存中的 `session` 对象，无需 CDP 连接或子进程通信。
- **极致安全**：AST 注入和全局变量限制提供了双重安全保障，即轻量又坚如磐石。
- **全栈兼容**：完美兼容 `LAUNCH`, `CONNECT`, `AUTO` 等所有浏览器启动模式（因为不依赖外部 CDP 端口）。

---

### 15. 动作与验证一体化 (Action-Verification Fusion)

**设计目标**：解决大模型操控浏览器时常见的“幻觉执行”（以为点击成功但实际被遮挡，或以为导航成功但实际遇到验证码拦截），赋予 Agent 人类级别的视觉纠错能力，同时避免独立调用视觉工具带来的高昂延迟和 Token 成本。

**架构设计**：
在 `browser_navigate_tool`、`browser_interact_tool` 和 `browser_execute_script_tool` 中提供 `verify_goal` 参数。当 Agent 传入该参数时，系统自动触发**三层极速视觉漏斗**：

1. **Layer 1: DOM 突变拦截 (0ms)**：利用 `MutationObserver`（或等效机制），如果 DOM 毫无变化，直接判定失败。
2. **Layer 2: 像素哈希校验 (dHash, 2ms)**：利用现有的 `FastComparator`，如果动作前后截图的哈希相似度 > 99%，直接判定失败，拦截 80% 无效的视觉大模型调用。
3. **Layer 3: 轻量级视觉打分 (~1s)**：只有通过前两层，才将新截图和 `verify_goal` 发给后端的轻量级视觉模型（如 GPT-4o-mini）。如果打分 < 4，将视觉模型的“失败理由”（如：“被弹窗遮挡”）作为纯文本返回给主控 Agent。

**核心优势**：
- **保护缓存**：主控 Agent 只接收纯文本失败理由，绝对保护了主模型的提示词缓存（Prompt Cache）。
- **极速低本**：后端毫秒级自动完成验证，省去了一整轮大模型对话的时间，前两层漏斗省下了大量 Vision Token 费用。
- **高鲁棒性**：将复杂长链路 Web 任务的成功率从 ~40% 飙升至 90%+。

### 16. Self-Healing Locators (定位自愈机制)

**设计目标**：彻底解决网页 DOM 结构频繁变动导致的 `RefNotFoundError` 和自动化中断。通过空间局部性和多维特征，在不消耗大模型 Token 和时间的情况下，实现微秒级的透明自动修复。

**架构设计**：
- **多维特征缓存**：在捕获 ARIA 快照时，在底层提取每个交互元素的 `bbox` (Bounding Box, x/y/width/height) 坐标，以及核心文本特征，存入 `RefInfo`。
- **浏览器侧极速匹配**：通过单次注入的 `_HEAL_JS`，在 Playwright `evaluate_all` 内执行欧式距离计算（限制于 200px 范围内）和文本包含惩罚得分。实现了相比 CDP 逐个查询数百倍的性能提升。
- **Semantic Veto (语义否决)**：内建高危词汇拦截库 (如 `delete`, `cancel`)。若旧按钮非危险而候选按钮为危险，系统会强行一票否决，从而彻底消除“找错按钮导致删库”的业务灾难。
- **跨层自愈传播**：在 `Interactor` 内完成透明的自我修复后，会抛出底层的 `LocatorSelfHealedEvent`。`Harness Bridge` 将其转化为 `LOCATOR_HEALED` SSE 应用事件并推送至前端 UI 进行通知展现。

---

### 17. Human Takeover (人类接管工具)

**设计目标**：当 Agent 遭遇无法自动化的场景（2FA、短信验证、支付网关、手写签名、企业 SSO MFA 推送等）时，主动暂停执行并请求用户通过 VNC/noVNC 直接操控浏览器完成操作。

**架构设计**：

```
Agent 推理 → browser_ask_human_tool(reason="请输入短信验证码")
  ↓ dispatch_custom_event("browser_takeover_requested", payload)
  ↓ langgraph.types.interrupt(hitl_payload)  ← Agent 暂停
  ...
Frontend ← SSE: browser_takeover_requested
  ↓ auto-open VNC/noVNC panel + 显示 reason 通知条
  ↓ 用户直接操作浏览器（输入验证码/完成支付）
  ↓ 用户点 "Done" 按钮
  ...
Frontend → POST /agents/agent-stream { resume_value: { action: "completed" } }
  ↓ Command(resume=resume_value) → interrupt() 返回 user_response
  ↓ dispatch_custom_event("browser_takeover_completed")
  ↓ Agent 恢复执行，截图观察当前页面状态
```

**核心特性**：
- **Agent 主动触发**：不是被动等待超时，而是 Agent 智能判断何时需要人类介入
- **统一 HITL 机制**：复用 LangGraph `interrupt()`/`Command(resume=...)` + SSE agent-stream resume，零额外基础设施
- **VNC 自动弹出**：前端收到 `browser_takeover_requested` SSE 事件后自动打开 VNC 面板（SaaS 通过 VncProxy，Local 连接 localhost:6080）
- **CAPTCHA 统一体验**：`CaptchaCoordinator` 检测到 CAPTCHA 时触发 `browser_takeover_requested`，无论解决成功或失败均触发 `browser_takeover_completed` 关闭 VNC 面板（载荷含 `success` 字段），前端统一处理
- **零 Prompt Cache 影响**：tool 返回纯文本摘要（用时、URL 变化、页面标题），不影响主模型缓存

**实现位置**：`tools/takeover.py` → `create_takeover_tool(session)`

---

## 竞品对比

### 功能覆盖

| 能力 | 我们 | Playwright MCP | browser-use | agent-browser |
|------|:---:|:---:|:---:|:---:|
| **iframe 穿透** | ✅ | ❌ | ❌ | ❌ |
| **三层角色分类** | ✅ | ❌ | ❌ | ❌ |
| **Cursor-interactive** | ✅ | ❌ | ❌ | ❌ |
| **反检测（Patchright/Camoufox）** | ✅ | ❌ | ❌ | ❌ |
| **语义感知 Diff** | ✅ | ❌ | ❌ | ❌ |
| **加密 Session Vault** | ✅ | ❌ | ❌ | ❌ |
| **三层域名过滤** | ✅ | ❌ | ❌ | ⚠️ 可绕过 |
| **零拷贝页面复用** | ✅ | ❌ | ❌ | ❌ |
| **MutationObserver变化检测** | ✅ | ❌ | ❌ | ❌ |
| **CAPTCHA 协调（可插拔）** | ✅ | ❌ | ⚠️ CDP 耦合 | ❌ |
| **Agent 触发人类接管** | ✅ | ❌ | ❌ | ❌ |

### 架构对比

| 维度 | 我们 | Playwright MCP | browser-use | agent-browser |
|------|------|---------------|-------------|--------------|
| **工具数量** | 8 | 24 | 8 | CLI |
| **Token 成本** | ~60 | ~480 | ~200 | N/A |
| **反检测** | ✅ Patchright / Camoufox | ❌ | ❌ | ❌（仅云端） |
| **LangChain 原生** | ✅ | ❌ 需适配器 | ❌ | ❌ |
| **独立使用** | ✅ 纯 Python | ❌ 需 MCP 运行时 | ❌ | ❌ 需 Go 二进制 |

---

## 使用示例

### 基本用法

```python
from myrm_agent_harness.toolkits.browser import BrowserSession
from myrm_agent_harness.toolkits.browser.pool import ContextType, get_global_browser_pool

# 获取全局浏览器池
pool = get_global_browser_pool()
await pool.warmup()

# 创建会话
session = BrowserSession(pool, ContextType.AGENT)

# 使用
await session.new_tab()
await session.navigate("https://example.com")
aria_tree, metadata = await session.snapshot()
await session.interact("click", "e0")
text = await session.extract_text()
await session.close()
```

---

## 代码清单

### 核心文件结构

```
browser/
├── captcha/
│   ├── protocols.py — CaptchaType, CaptchaStatus, CaptchaInfo, CaptchaSolveResult, CaptchaSolver Protocol, CaptchaHandleResult
│   ├── detector.py — 页面级 CAPTCHA 检测（HTML 正则，两层模式）
│   ├── coordinator.py — CAPTCHA 协调状态机（asyncio.Event 暂停/恢复）
│   └── manual_solver.py — 默认手动求解器（轮询检测 CAPTCHA 消失）
├── tools/
│   ├── __init__.py — 8 LangChain @tool 导出与 create_browser_tools 工厂
│   ├── navigate.py — browser_navigate_tool
│   ├── snapshot.py — browser_snapshot_tool
│   ├── interact.py — browser_interact_tool（含 Semantic DOM Guard）
│   ├── extract.py — browser_extract_tool
│   ├── manage.py — browser_manage_tool
│   ├── execute_script.py — browser_execute_script_tool（含 AST 特权API Scanner + HITL 门禁）
│   ├── takeover.py — browser_ask_human_tool（人类接管，LangGraph interrupt + VNC 自动弹出）
│   ├── inspect.py — browser_inspect_tool
│   ├── _semantic_risk.py — 语义 DOM 风险分类（纯函数）
│   └── common.py — 工具共享工具函数
├── pool/
│   ├── browser_pool.py (716 行) — GlobalBrowserPool（全局调度中枢）
│   ├── browser_launcher.py (~525 行) — BrowserLauncher（Browser 启动器 + Zero-config Chromium 自动安装 with CDN mirror fallback + Camoufox 指纹持久化 + 损坏自愈）
│   ├── context_factory.py (156 行) — ContextFactory（Context 工厂）
│   └── page_pool.py (195 行) — PagePool
├── diff/
│   ├── types.py — ComparisonResult Protocol + FastComparisonResult + AccurateComparisonResult
│   ├── fast_comparator.py — FastComparator（dHash，~2ms）
│   └── accurate_comparator.py — AccurateComparator（Canvas API，~100ms）
├── snapshot/
│   ├── aria_types.py (119 行) — 数据类型定义
│   ├── aria_acquisition.py (182 行) — Layer 1：ARIA 树获取
│   ├── aria_parser.py (116 行) — Layer 2：YAML 解析
│   ├── aria_enhancer.py (237 行) — Layer 3：树增强
│   ├── aria_renderer.py (99 行) — Layer 4：文本渲染
│   ├── parser.py (323 行) — 向后兼容接口
│   ├── frame_snapshot.py (378 行) — 单 Frame 增量快照管理
│   ├── page_snapshot.py (222 行) — 多 Frame 聚合快照管理
│   └── observer_scripts.py (196 行) — JavaScript 脚本
├── session/
│   ├── browser_session.py — BrowserSession 聚合根（tab/navigate/snapshot/interact/网络/下载）
│   ├── browser_session_extraction_mixin.py — 内容提取、vision fallback、截图对比
│   ├── browser_session_page_mixin.py — viewport、dialog、evaluate 等页面级 API
│   ├── browser_session_persistence_mixin.py — SessionVault 持久化 API
│   ├── browser_session_recording_mixin.py — trace/HAR 录制控制
│   ├── tab_controller.py — TabController
│   ├── snapshot_manager.py — SnapshotManager（委托 FrameRegistry）
│   ├── interactor.py — Interactor
│   ├── extractor.py — Extractor
│   ├── structured_extractor.py — LLM + JSON Schema 结构化提取
│   ├── page_analyzer.py — 两阶段快照架构
│   ├── session_persistence.py — SessionPersistence
│   ├── session_lifecycle_hook.py — SessionLifecycleHookProtocol
│   ├── session_memory_bridge.py — SessionMemoryBridge
│   ├── network_intelligence.py — CDP 懒加载 API 响应体检索
│   ├── network_logger.py — 网络请求日志
│   ├── vision_verifier.py — 三层视觉验证
│   ├── dialog_manager.py — JS dialog 生命周期
│   ├── download_manager.py — 文件下载
│   └── consent_dismisser.py — Cookie consent 自动 dismiss
│   （Navigator 位于 `navigation/` 包，BrowserSession 与 BrowserFetcher 共用）
├── domain_filter.py (317 行) — 四层域名过滤（CSP + HTTP + 主线程硬化 + CDP）
├── session_vault.py (678 行) — 加密 Session 存储（O(1) LRU + 内存限制 + 并发锁 + Metrics + 批量 API）
├── exceptions.py (约 150 行) — 异常类型
└── retry_policy.py (约 200 行) — 重试策略
```

**总计**：约 4,100 行核心代码，SOLID 原则，单一职责，高度模块化。

---

## 参考资料

- [Patchright 官方文档](https://github.com/Kaliiiiiiiiii-Vinyzu/patchright)
- [Playwright ARIA Snapshot](https://playwright.dev/docs/aria-snapshots)
- [MCP Playwright](https://github.com/microsoft/playwright-mcp)
- [agent-browser](https://github.com/Kernel-Dirichlet/agent-browser)
- [browser-use](https://github.com/browser-use/browser-use)
