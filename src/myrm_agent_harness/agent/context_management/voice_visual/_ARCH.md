# voice_visual/

语音问答视觉感知与屏幕截图上下文自动注入套件（Item 303: VoiceScreenshotContextAwarenessSuite）。

## 职责

在语音交互中启发式自动探测视觉指代意图（如“这个报错”、“看下这段代码”、“这个按钮为什么没反应”等），在请求下发至大模型前自动挂载当前屏幕截图上下文并注入结构化引导提示，消除语音交互缺乏视觉信息导致答非所问的问题。

## 文件清单

| 文件 | 职责 |
|---|---|
| `voice_visual_types.py` | 视觉意图类别、判定结果、截图上下文模型与配置声明（0 Any） |
| `voice_visual_detector.py` | 毫秒级启发式规则与正则是别检测器，支持中英双语指代提取 |
| `voice_visual_injector.py` | 多模态上下文封装器与基于瓦片网格的图像 Token 消耗估算器 |
| `voice_screenshot_context_suite.py` | 统一外观门面（Facade），统筹意图检测、截图注水与完整轮次转换 |
| `__init__.py` | 外部公共 API 导出与契约暴露 |
