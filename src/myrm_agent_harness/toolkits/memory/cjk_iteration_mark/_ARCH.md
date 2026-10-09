# CJK Iteration Mark Recall Disambiguation Architecture (_ARCH.md)

## 1. 模块定位
本模块是长期记忆系统中针对东亚语言（日文及含汉字叠字文本）叠字符号「々」（U+3005）的消歧召回与分词增强引擎，直接对标 `mnemosyne-oss #1022`。

## 2. 第一性原理与核心目标
传统搜索引擎或分词器对「々」的处理存在严重缺陷：
1. **分词撕裂与 0 命中**：将 `々` 当作标点符号过滤，导致「人々」变成单个「人」，用户搜「人人」或「ひとびと」时完全无法召回；
2. **粗暴盲目替换**：在遇到假名、非汉字或链式叠字时产生错误替换与越界崩溃。

本模块构建前驱汉字链式解析与三维锚点消歧体系（Chained Han Resolution & Tri-Token Anchor Model）：
- 严格限定仅在同一个连续 CJK Run 内部由紧邻合法汉字（`\u4e00-\u9fff`）充当前驱；
- 链式 mark（`XX々々`）基于 resolved 汉字链式推导；
- 假名（平假名/片假名）、韩文谚文、标点符号及孤立 `々` 绝不错误充当前驱；
- 提取三维 Token 矩阵（Raw Tokens / Normalized Tokens / Anchor Tokens），实现双向 100% 召回且零歧义误伤。

## 3. 分形架构规范
- `models.py`: 严格强类型领域实体，禁止任何 `typing.Any`；
- `resolver.py`: 链式前驱汉字解析器与三维 Bigram 生成器；
- `matcher.py`: 双向多路相关度评分匹配器；
- `facade.py`: 对外统一门面与全局单例导出。
