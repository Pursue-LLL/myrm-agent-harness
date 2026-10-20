# myrm_agent_harness/observability/rate_limit_governor/

## 架构概述

客户端主动限流预测阀门、按模型动态配额自适应调度与零 429 顺滑放行引擎。上级文档：[../_ARCH.md](../_ARCH.md)。

## 文件清单

| 文件 | 地位 | 职责 | I/O/P |
|------|------|------|-------|
| `models.py` | 模型 | 响应头配额快照、模型速率限制配置、主动整形放行决策与子任务配额切片契约 | ✅ |
| `header_sniffer.py` | 侦听器 | 多厂商 (OpenAI/Anthropic/DeepSeek) HTTP 响应头配额侦听与权威额度时钟标准化 | ✅ |
| `pacing_governor.py` | 阀门 | 60 秒滑动窗口令牌桶、前置微延迟平滑削峰 (200~500ms) 与零 429 顺滑放行执行器 | ✅ |
| `quota_slicer.py` | 切片器 | 多并发子 Agent 配额按切片动态隔离分配，实现工作区计费隔离与防贪婪任务撞墙 | ✅ |
| `__init__.py` | 门面 | 聚合导出主动限流预测阀门与子任务配额套件全部核心契约与管理类 | ✅ |
