# Multimodal Trace Module Architecture

## 概述
多模态调用链媒体对象引用解耦与三步排查（输入-执行-反馈）套件：
- 避免直接将大尺寸 Base64 塞入 Trace Span 导致日志截断崩溃或存储成本暴增；
- 引入媒体引用对象 `MediaReference`（URI, SHA256, MIME, FileSize）解耦存储与追踪；
- 支持 4 态可见性生命周期（`ready`, `uploading`, `expired`, `purged`）；
- 对齐 OpenTelemetry GenAI 多模态标准规范 `parts`；
- 支持将异常用例施加加星锁沉淀为多模态黄金评测样本集（Golden Eval Pinning）。

## 文件列表

| 文件名 | 类型 | 职责说明 | 状态 |
| :--- | :--- | :--- | :--- |
| `models.py` | 实体 | 媒体模态、4 态可见性、媒体引用、OTel GenAI 消息分片与 3 步排查不可变模型 | ✅ |
| `manager.py` | 管理器 | 线程安全多模态 Trace 与媒体引用注册表、可见性自诊断、黄金样本加星锁与过滤查询 | ✅ |
| `__init__.py` | 门面 | 聚合导出模块内所有模型与管理器单例获取函数 | ✅ |
