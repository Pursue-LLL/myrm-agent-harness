# toolkits/mobile_adb 模块架构

## 架构概述

移动端 Wireless ADB 控制工具包。提供 Android 设备的无线发现、ADB 命令执行、UI 层次结构解析与语义化交互支持，可作为通用能力库或通过适配器包装为 LangChain 工具供 Agent 调用。

## 文件清单

| 文件 | 地位 | 职责 | I/O/P |
|------|------|------|-------|
| `__init__.py` | 包门面 | 导出 `MobileSession`、`AdbDeviceDriver`、`MobileUIParser`、`create_mobile_adb_tools` 等核心符号 | ✅ |
| `types.py` | 领域模型 | 定义 `MobileDeviceConnectionStatus`、`MobileUIElement`、`MobileDeviceState`、`MobileActionResult` | ✅ |
| `driver.py` | 驱动核心 | 底层异步 ADB 命令执行器，管理设备连接与 low-level 执行 | ✅ |
| `parser.py` | 解析器 | 解析 Android dump 结构与节点属性，构建 `MobileUIElement` 层次结构 | ✅ |
| `session.py` | 会话编排 | 移动端设备交互核心会话管理器，协调驱动执行与状态同步 | ✅ |
| `mobile_agent_tools.py` | Agent 适配器 | LangChain `StructuredTool` 适配层，将 session 操作包装为 Agent 工具 | ✅ |

## 模块依赖

- 依赖 `core/`、`utils/` 基础能力。
- 严禁依赖 `agent/`（零耦合）。
