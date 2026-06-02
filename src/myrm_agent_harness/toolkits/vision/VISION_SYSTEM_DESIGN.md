# Vision System Design - Media Adaptive Degradation Routing

## 设计目标

为不支持视觉/视频的主模型提供图像和视频自适应降级路由能力，确保多模态请求能够正确处理，同时为用户提供友好的实时状态反馈。

## 核心特性

1. **自动检测与路由**：根据主模型的 `supports_vision` / `supports_video` 标志自动判断是否需要 fallback
2. **辅助模型调用**：使用配置的 `visionFallbackModel` 将图像/视频转为文本描述
3. **实时状态通知**：通过 SSE 事件（`analyzing_image/video` + `analyzing_image/video_clear`）向前端通知处理状态
4. **优雅降级**：失败时返回友好的错误信息，不影响整体请求流程
5. **视频双策略**：支持原生视频的模型（如 Gemini）直传，不支持的通过 ffmpeg 帧提取 + 视觉模型分析

## 系统架构

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Frontend Layer                               │
├─────────────────────────────────────────────────────────────────────┤
│ - MessageBox: UI status indicator (mediaAnalysisStatus)              │
│ - messageStreamHandler: Process SSE events (analyzing_image/video)  │
└──────────────────────────┬──────────────────────────────────────────┘
                           │ SSE Stream
                           ▼
┌─────────────────────────────────────────────────────────────────────┐
│                       Server Business Layer                          │
├─────────────────────────────────────────────────────────────────────┤
│ - chat_utils.py::_process_image_item / _process_video_item          │
│   • Check supports_vision / supports_video flag                     │
│   • Emit SSE event: analyzing_image / analyzing_video               │
│   • Call VisionFallbackEngine / VideoAnalysisEngine                 │
│   • Replace media with text description                             │
│   • Emit SSE event: analyzing_image_clear / analyzing_video_clear   │
└──────────────────────────┬──────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────────┐
│                         Harness Layer                                │
├─────────────────────────────────────────────────────────────────────┤
│ - VisionFallbackEngine (toolkits/vision/fallback_engine.py)        │
│   • Image compression (if too large)                                │
│   • Call vision model via LiteLLM                                   │
│   • Return text description                                         │
│ - VideoAnalysisEngine (toolkits/vision/video_analysis_engine.py)   │
│   • Native video pass-through (for video-capable models)            │
│   • ffmpeg frame extraction fallback (scene detection + uniform)    │
│   • Return text description via vision fallback                     │
└─────────────────────────────────────────────────────────────────────┘
```

## 核心组件

### 1. VisionFallbackEngine (Harness Layer)

**位置**: `myrm_agent_harness/toolkits/vision/fallback_engine.py`

**职责**:
- 接收 Base64 图像数据和 MIME 类型
- 如果图像过大，自动压缩（使用 `ImageCompressor`）
- 调用 vision model 生成文本描述
- 返回描述文本

**关键方法**:
```python
async def describe_image_b64(
    self, 
    image_b64: str, 
    mime_type: str = "image/png"
) -> str
```

### 2. _process_image_item (Server Layer)

**位置**: `myrm-agent-server/app/core/utils/chat_utils.py`

**职责**:
- 判断是否需要 vision fallback
- 调用 `VisionFallbackEngine`
- 发送 SSE 状态事件
- 处理异常并返回友好错误信息

**关键逻辑**:
```python
if not supports_vision and vision_fallback_model_cfg:
    # 1. Emit SSE: analyzing_image
    # 2. Call VisionFallbackEngine
    # 3. Emit SSE: analyzing_image_clear
    # 4. Replace image with text description
```

### 3. Frontend Status Display

**MessageBox Component** (`myrm-agent-frontend/src/components/ui/message-box/MessageBox.tsx`):
- 检查 `message.mediaAnalysisStatus`（统一字段支持 `analyzing_image` / `analyzing_video`）
- 渲染精美的状态指示器（渐变背景 + 旋转动画 + i18n 文本）

**messageStreamHandler** (`myrm-agent-frontend/src/store/chat/messageStreamHandler.ts`):
- 监听 SSE 事件 `type: "status"` + `step_key: "analyzing_image" | "analyzing_video"`
- 设置/清除 message 的 `mediaAnalysisStatus` 字段

## 配置示例

```json
{
  "defaultModelConfig": {
    "baseModel": {
      "primary": {
        "providerId": "openai-compatible",
        "model": "deepseek-v4-flash"
      }
    },
    "visionFallbackModel": {
      "providerId": "openai-compatible",
      "model": "qwen-vl-plus"
    }
  },
  "customModelInfo": {
    "openai-compatible/deepseek-v4-flash": {
      "supports_vision": false
    },
    "openai-compatible/qwen-vl-plus": {
      "supports_vision": true
    }
  }
}
```

## 技术细节

### 1. 图像压缩策略

如果原始图像超过 LiteLLM 的尺寸限制，`VisionFallbackEngine` 会自动调用 `ImageCompressor` 进行压缩：

- 最大分辨率：2000x2000
- 质量：85%
- 格式：保持原格式（或转为 JPEG）

### 2. SSE 事件流程

```
Client                    Server
  |                         |
  |--- Image + Message ---> |
  |                         | (Check supports_vision = false)
  |<--- analyzing_image --- |
  |                         | (Call VisionFallbackEngine)
  |                         | ...vision model processing...
  |<-- analyzing_image_clear|
  |<--- Content Stream ---  | (with text description)
  |                         |
```

### 3. 错误处理

所有 vision fallback 异常都被捕获并转换为友好的文本消息：

```python
try:
    fallback_text = await engine.describe_image_b64(...)
    return {"type": "text", "text": fallback_text}
except Exception as e:
    logger.warning(f"Vision fallback failed: {e}")
    return {"type": "text", "text": f"[Image Analysis Failed: {e}]"}
```

## 测试覆盖

### Backend API Test

**工具**: `httpx` 直接调用 `/api/v1/agents/agent-stream`

**验证点**:
- ✅ SSE `analyzing_image` 事件
- ✅ SSE `analyzing_image_clear` 事件
- ✅ Vision fallback 逻辑触发

### Frontend E2E Test

**工具**: Playwright

**文件**: `myrm-agent-server/tests/misc/test_vision_simple.py`

**验证点**:
- ✅ 图片上传
- ✅ 消息发送
- ✅ SSE 事件接收
- ✅ DOM UI 渲染（"分析图片中..."）

## 已知限制与未来优化

### 当前能力

1. 多图/视频并发分析（asyncio.gather）
2. MD5 hash 字典缓存（避免重复分析）
3. 视频帧提取（ffmpeg 场景检测 + 均匀采样降级）
4. 图片自动压缩（超尺寸自适应）
5. 视频大小限制（100MB）和格式验证

## 参考资料

- **LiteLLM Vision API**: https://docs.litellm.ai/docs/vision
- **SSE (Server-Sent Events)**: https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events
- **Playwright E2E Testing**: https://playwright.dev/python/

