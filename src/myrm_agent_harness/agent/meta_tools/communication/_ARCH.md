# communication/

## 架构概述
提供智能体长任务执行期间的主动异步通信能力，包含非阻塞进度上报、里程碑通报与带预案澄清提问。

详细设计请参考 [../META_TOOLS_SYSTEM.md](../META_TOOLS_SYSTEM.md)。

## 文件清单

| 文件 | 地位 | 职责 | I/O/P |
| --- | --- | --- | --- |
| `__init__.py` | 核心 | 模块导出入口，暴露 `create_send_user_message_async_tool` 等接口 | ✅ |
| `send_user_message_async_tool.py` | 核心 | 非阻塞异步通信元工具、线程安全滑动窗口限流器与事件分发 | ✅ |

## 模块依赖

- `langchain_core.tools` (LangChain 工具装饰器)
- `langchain_core.callbacks.manager` (SSE 自定义事件派发)
- `pydantic` (输入校验与元数据定义)

