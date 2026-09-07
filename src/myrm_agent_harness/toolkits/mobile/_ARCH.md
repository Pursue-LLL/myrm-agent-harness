# Mobile ADB Bridge Toolkit Architecture

## 1. 模块定位与职责边界 (Architectural Positioning)
`myrm_agent_harness.toolkits.mobile` 是 Myrm 框架内置的 Android 移动端自动化桥接工具包，遵循 `toolkits/_ARCH.md` 规范：
- **框架通用能力**：独立于具体的业务 Server 和 Agent Runtime，提供原生 ADB/Wireless Debugging 连接、UI 层次解析、手势控制与安全防护网关。
- **无状态与轻量化**：基于原生 `adb` 进程/流式通信，不强绑重型三方守护进程（如 Appium Server），启动极速，开箱即用。
- **零 Token 污染**：提供纯 Python API，并通过 LangChain BaseTool 工厂按需懒加载暴露给 Agent，保障 Prompt Cache 命中率。

## 2. 核心子模块划分 (Submodules)
- `types.py`: 数据模型（`MobileDevice`, `MobileUIElement`, `MobileActionResult`, `MobileConfig`）。
- `protocols.py`: 接口契约与依赖倒置协议（`DeviceManagerProtocol`, `UIInspectorProtocol`, `InputControllerProtocol`, `SafetyBarrierProtocol`）。
- `device_manager.py`: 设备发现、状态检测、无线配对连接与 mDNS 服务探活。
- `inspector.py`: UIAutomator XML 结构化解析、坐标仿射归一化（0.0~1.0 相对坐标系）与高效 WebP/PNG 屏幕截图。
- `input_controller.py`: 物理/归一化坐标点击、平滑滑动、Base64 IME 广播全字符集/中文输入、按键注入与 App 启动。
- `safety.py`: 敏感页面阻断器（Sensitive Action Barrier），识别密码输入框、支付结算界面与高危授权弹窗，触发 HITL 人机协同屏障。
- `tools.py`: LangChain 格式的 Agent 外部工具集合封装与工具工厂函数。

## 3. 安全与防护规范 (Safety Guidelines)
1. **密码与支付防误触**：任何包含 `password`、`payment`、`pay`、`pwd` 等特征的输入框或结算按钮，默认触发安全阻断并提示 Agent 请求人工授权。
2. **命令注入防范**：所有 ADB 指令参数必须经过类型校验与 shell 转义（使用 `shlex.quote`），杜绝恶意字符注入。
3. **超时与孤儿进程自愈**：所有子进程调用严格设置 10~30s 超时保护，自动回收异常挂起的 adb 进程。
