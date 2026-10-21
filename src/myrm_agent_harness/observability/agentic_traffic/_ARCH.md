# agentic_traffic/

## 架构概述

AI Agent 流量精准解构、跳出归因与静默审判可观测性套件。上级文档：[../_ARCH.md](../_ARCH.md)。
聚焦破除传统 Web 分析平台将 AI Agent 粗暴标记为 100% 跳出匿名垃圾流量的失明痛点：
1. **Agent 访客精准识别**：基于 User-Agent、请求头与毫秒时序精准识别 Cursor / Claude Code / Windsurf / Aider / Cline / OpenClaw / Myrm；
2. **AEO 跳出根因诊断探针**：诊断文档页面 Token 是否撑爆 >20k、是否缺乏 `/llms.txt`、前 500 Token 是否缺少核心代码示例、是否为纯 SPA 客户端空白页；
3. **转化漏斗分析**：Discovered ➔ Context Absorbed ➔ Sandbox Probed ➔ Adopted 四阶梯生命周期透视。

## 文件清单

| 文件 | 地位 | 职责 | I/O/P |
|------|------|------|-------|
| `models.py` | 实体 | 定义 AgentType, AbandonmentReason, FunnelStage, 访问记录与汇总报告模型 | ✅ |
| `traffic_classifier.py` | 算法 | 基于 UA 特征、自定义 Header 与请求时序的多维智能体流量分类器 | ✅ |
| `abandonment_sentinel.py` | 探针 | 页面 AEO 指标诊断探针、Token 估算与静默放弃根因分析器 | ✅ |
| `analytics_engine.py` | 核心 | 访问流水记录、转化漏斗多阶梯聚合与流失原因分布统计引擎 | ✅ |
| `__init__.py` | 门面 | 聚合导出模块内所有组件与类型定义 | ✅ |
