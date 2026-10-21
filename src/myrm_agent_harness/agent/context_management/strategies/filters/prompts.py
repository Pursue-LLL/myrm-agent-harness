"""语义过滤器的 Prompt 模板

定义用于 LLM 摘要生成的提示词。

设计理念（来自 Manus）：
- 摘要的目的是帮助模型**理解文件内容**，而不是"替代"原始数据
- 模型可以随时通过文件路径读取原始内容
- 摘要应该告诉模型：文件里有什么、是否需要读取、如何高效读取

[INPUT]
- (none)

[OUTPUT]
- (none)

[POS]
Prompts.
"""

# 内容描述 Prompt（强调可恢复性）
CONTENT_DESCRIPTION_PROMPT = """你是一个内容分析助手。
你的任务是描述内容结构，以便模型决定是否需要稍后读取完整文件。

完整内容已保存到文件。模型可以随时使用 file_read_tool 读取。

<content_preview>
{content}
</content_preview>

请用 JSON 格式描述这个内容：
{{
    "content_type": "内容类型（文章/文档/数据/代码等）",
    "main_topic": "这个内容是关于什么的（一句话）",
    "structure": "内容如何组织（章节/段落/列表等）",
    "key_sections": ["章节1标题或描述", "章节2", ...],
    "reading_suggestion": "如果模型需要特定信息，应该先读哪部分"
}}

重要提示：
- 这不是用来替代原始内容的摘要
- 模型会在需要时读取完整文件
- 重点描述文件里有什么，而不是提取信息
- key_sections 最多 5 项
"""

# HTML 内容描述 Prompt
HTML_DESCRIPTION_PROMPT = """你是一个网页内容分析助手。
你的任务是描述网页结构，以便模型决定是否需要稍后读取完整内容。

完整 HTML 已保存到文件。模型可以随时使用 file_read_tool 读取。

<html_preview>
{content}
</html_preview>

请用 JSON 格式描述这个网页：
{{
    "page_title": "页面标题",
    "page_type": "页面类型（文章/文档/产品页/搜索结果等）",
    "main_topic": "这个页面是关于什么的（一句话）",
    "main_sections": ["章节1", "章节2", ...],
    "has_useful_links": true/false,
    "reading_suggestion": "如果模型需要特定信息，应该先读哪部分"
}}

重要提示：
- 这不是用来替代原始内容的摘要
- 模型会在需要时读取完整文件
- 重点描述页面结构，而不是提取所有信息
- main_sections 最多 5 项
"""

# Markdown 内容描述 Prompt
MARKDOWN_DESCRIPTION_PROMPT = """你是一个文档分析助手。
你的任务是描述文档结构，以便模型决定是否需要稍后读取特定章节。

完整 Markdown 已保存到文件。模型可以随时使用 file_read_tool 读取。

<markdown_preview>
{content}
</markdown_preview>

请用 JSON 格式描述这个文档：
{{
    "document_title": "文档标题（来自第一个标题）",
    "document_type": "文档类型（教程/API参考/指南/README等）",
    "main_topic": "这个文档是关于什么的（一句话）",
    "table_of_contents": ["# 标题1", "## 标题2", ...],
    "reading_suggestion": "常见用例应该先读哪个章节"
}}

重要提示：
- 这不是用来替代原始内容的摘要
- 模型会在需要时读取完整文件
- 重点描述文档结构，特别是标题
- table_of_contents 最多列出 10 个主要标题
"""

# 纯文本内容描述 Prompt
PLAIN_TEXT_DESCRIPTION_PROMPT = """你是一个文本分析助手。
你的任务是描述文本内容，以便模型决定是否需要稍后读取完整文件。

完整文本已保存到文件。模型可以随时使用 file_read_tool 读取。

<text_preview>
{content}
</text_preview>

请用 JSON 格式描述这个文本：
{{
    "content_type": "文本类型（日志/数据/散文/代码输出等）",
    "main_topic": "这个文本是关于什么的（一句话）",
    "structure": "文本如何组织（段落/行/记录等）",
    "notable_patterns": ["模式1", "模式2", ...],
    "reading_suggestion": "如何在这个文本中找到特定信息"
}}

重要提示：
- 这不是用来替代原始内容的摘要
- 模型会在需要时读取完整文件
- 重点描述文件里有什么以及如何组织
- notable_patterns 最多 3 项
"""
