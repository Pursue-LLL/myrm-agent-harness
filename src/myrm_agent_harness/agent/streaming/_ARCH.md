# Streaming Checkpoint & Recovery Architecture

## 架构概述

提供流式中断安全捕获、最长公共前缀（LCP）动态去重清洗以及无缝断点续接引导能力。

## 文件清单

| 文件 | 地位 | 职责 |
| --- | --- | --- |
| `__init__.py` | 入口 | 模块导出 |
| `resume_checkpoint.py` | 核心 | 流式安全断点抓取、字符级去重清洗、Prompt 缓存无损续传引导词生成 |
