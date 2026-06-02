# 工具安全包装开发者指南

> 何时在工具层使用 `wrap_with_external_sources_tag()` 和 `wrap_with_tool_output_tag()`

---

## 核心原则

**外部数据必须包装，内部数据无需包装。**

---

## 包装决策树

```
工具返回的数据来自哪里？
├─ 外部不可信来源（网页、第三方 API、用户上传文件）
│  └─ ✅ 必须包装
│     └─ 使用 wrap_with_external_sources_tag(content, source="tool_name")
│
└─ 内部可信来源（系统记忆、Agent 自身、用户自己执行的代码）
   └─ ❌ 无需包装
```

---

## 具体场景判断

### ✅ 必须包装的工具

| 工具类型 | 示例 | 原因 | 使用方法 |
|---------|------|------|---------|
| **Web 搜索** | `web_search` | 搜索结果来自不可控的外部网站 | `wrap_with_external_sources_tag(results, source="web_search")` |
| **Web 抓取** | `web_fetch` | 网页内容可能包含恶意指令 | `wrap_with_external_sources_tag(html_content, source="web_fetch")` |
| **浏览器工具** | `browser_snapshot_tool`, `browser_extract_tool` | 网页内容不可信 | `wrap_with_external_sources_tag(page_content, source="browser")` |
| **知识库查询** | `wiki_query_tool` | 知识库内容可能来自外部摄取 | `wrap_with_external_sources_tag(wiki_content, source="wiki")` |
| **MCP 远程数据** | MCP 工具（如 `github_api`, `slack_api`） | 第三方 API 返回的数据不可信 | 框架层统一处理（工具层无需单独包装） |

### ❌ 无需包装的工具

| 工具类型 | 示例 | 原因 |
|---------|------|------|
| **代码执行** | `bash`, `python`, `code_execution` | 执行的是用户自己的代码，风险来源是用户自己 |
| **文件操作** | `file_read`, `file_write`, `file_list` | 读取的是用户自己的文件 |
| **记忆系统** | `memory_recall_tool`, `memory_save_tool` | 记忆数据已经过审核和存储，是可信的 |
| **Agent 委托** | `delegate_task_tool`, `spawn_subagent` | Agent 之间的内部通信，是可信的 |
| **系统工具** | `goals`, `cron`, `tasks` | 系统内部数据，是可信的 |

---

## 安全防护层级

使用 `wrap_with_external_sources_tag()` 或 `wrap_with_tool_output_tag()` 包装后，数据将获得 **5 层安全防护**：

1. **L1: Unicode Folding** — 26种角括号规范化，防止视觉欺骗
2. **L2: 不可见字符过滤** — 13类零宽字符剥离，防止隐写攻击
3. **L3: 可疑模式检测** — 20种注入模式检测（中英双语）
4. **L4: 随机边界 ID** — 不可预测的边界标记，防止伪造
5. **L5: 安全提示前缀** — 指示 LLM 不执行内容中的指令

---

## 实现示例

### ✅ 正确示例：Web 搜索工具

```python
from myrm_agent_harness.utils.context_format import wrap_with_external_sources_tag

@tool("web_search")
async def web_search(query: str) -> str:
    results = await search_engine.search(query)
    formatted_results = format_search_results(results)
    
    # 包装外部数据
    return wrap_with_external_sources_tag(
        formatted_results,
        source="web_search"
    )
```

### ❌ 错误示例：记忆召回工具

```python
# 错误！记忆数据是可信的，不需要包装
@tool("memory_recall_tool")
async def memory_recall_tool(query: str) -> str:
    memories = await memory_store.query(query)
    formatted_memories = format_memories(memories)
    
    # ❌ 不要这样做！
    return wrap_with_external_sources_tag(
        formatted_memories,
        source="memory"
    )
```

---

## 两种包装函数的区别

### `wrap_with_external_sources_tag()`

- **用途**：外部数据源（搜索结果、网页内容、Wiki、MCP远程数据）
- **效果**：触发引用规则，LLM 需要添加引用标记【1】【2】
- **边界标记**：`<<<UNTRUSTED_DATA id="...">>>`

```python
from myrm_agent_harness.utils.context_format import wrap_with_external_sources_tag

wrapped = wrap_with_external_sources_tag(content, source="web_search")
```

### `wrap_with_tool_output_tag()`

- **用途**：工具执行结果（代码输出、文件内容）
- **效果**：仅防止 prompt injection，不触发引用规则
- **边界标记**：`<<<TOOL_OUTPUT id="...">>>`
- **注意**：目前框架内**未使用**此函数，保留用于未来扩展

```python
from myrm_agent_harness.utils.context_format import wrap_with_tool_output_tag

wrapped = wrap_with_tool_output_tag(content)
```

---

## 检查清单

在实现新工具时，问自己以下问题：

1. ✅ **数据来源**：数据来自外部（网页、第三方 API）还是内部（系统记忆、用户文件）？
2. ✅ **风险评估**：数据是否可能包含恶意指令？
3. ✅ **已有先例**：类似的工具是如何处理的？
4. ✅ **测试验证**：是否有单元测试验证安全包装？

---

## 参考资料

- **核心实现**：`myrm_agent_harness/agent/security/detection/content_boundary.py`
- **工具层接口**：`myrm_agent_harness/utils/context_format.py`
- **已有示例**：
  - `toolkits/web_search/web_search_agent_tools.py`
  - `toolkits/web_fetch/web_fetch_agent_tools.py`
  - `toolkits/wiki/wiki_agent_tools.py`
  - `toolkits/browser/tools/` (snapshot.py, extract.py)

---

## 常见问题

### Q1: bash 工具输出需要包装吗？

**A**: 不需要。bash 执行的是用户自己的命令，风险来源是用户自己，包装无法阻止用户执行恶意命令。

### Q2: MCP 工具输出需要包装吗？

**A**: 理论上需要，但目前框架层尚未实现统一的 MCP 工具输出包装机制。这是一个独立的、更大的任务，需要在框架层（Agent 执行引擎）而不是工具层实现。

### Q3: 包装会影响性能吗？

**A**: 影响极小（< 1ms）。Unicode 折叠、字符过滤和模式检测都是高效的字符串操作，对工具调用的整体性能影响可忽略不计。

### Q4: 包装会增加 token 消耗吗？

**A**: 会，但非常少。安全提示前缀约 15-30 tokens，边界标记约 10 tokens，对于典型的工具输出（数百到数千 tokens）来说占比极低（< 5%）。

---

## 总结

**核心规则：外部数据必须包装，内部数据无需包装。**

遵循本指南，确保 MyrmAgent 的安全防护始终保持世界顶尖水平。
