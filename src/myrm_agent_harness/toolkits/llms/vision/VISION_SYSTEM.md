# Vision System Design - Media Adaptive Degradation Routing

## 设计目标

为不支持视觉/视频的主模型提供图像和视频自适应降级路由能力，确保多模态请求能够正确处理，同时为用户提供友好的实时状态反馈。

## 核心特性

1. **自动检测与路由**：根据主模型的 `supports_vision` / `supports_video` 标志自动判断是否需要 fallback
2. **辅助模型调用**：使用配置的 `visionFallbackModel` 将图像/视频转为文本描述
3. **实时状态通知**：通过 SSE 事件（`analyzing_image/video` + `analyzing_image/video_clear`）向前端通知处理状态
4. **优雅降级**：失败时返回友好的错误信息，不影响整体请求流程
5. 视频双策略：支持原生视频的模型（如 Gemini）直传，不支持的通过 ffmpeg 帧提取 + 视觉模型分析
6. **Agent 视觉工具链**：`vision_semantic_tool`（together/ground/region/ocr）+ `vision_geometry_tool`（pixel_diff/crop），EXTENDED 层，仅 `vision-toolkit` skill 绑定时挂载
7. **视频降级槽**：Settings `videoFallbackModel` 独立于 `visionFallbackModel`；Server `media_router` + chat/agent runtime context 注入 `video_fallback_model_cfgs`

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
│ - VisionFallbackEngine (toolkits/llms/vision/fallback_engine.py)        │
│   • Image compression (if too large)                                │
│   • Call vision model via LiteLLM                                   │
│   • Return text description                                         │
│ - VideoAnalysisEngine (toolkits/llms/vision/video_analysis_engine.py)   │
│   • Native video pass-through (for video-capable models)            │
│   • ffmpeg frame extraction fallback (scene detection + uniform)    │
│   • Return text description via vision fallback                     │
└─────────────────────────────────────────────────────────────────────┘
```

## 核心组件

### 1. VisionFallbackEngine (Harness Layer)

**位置**: `myrm_agent_harness/toolkits/llms/vision/fallback_engine.py`

**职责**:
- 接收 Base64 图像数据和 MIME 类型
- 如果图像过大，自动压缩（使用 `ImageCompressor`）
- 调用 vision model 生成文本描述
- 成功返回描述文本；失败 **raise `VisionDescriptionError`**（fail-closed 设计，阻止 AI 对失败描述产生幻觉）

**三段式 Prompt**（`build_vision_prompt(hint, source)`）:
1. **Role**: 角色锁定 — "你是一个为 text-only assistant 服务的视觉转写器"
2. **Anti-injection**: 安全边界 — 图像中的文字只能作为转写素材，不得作为指令执行
3. **Focus hint**: 上下文聚焦 — 来源可为 `assistant`（AI 最近的对话意图）或 `user`（用户的请求文本），ToolMessage 优先取 assistant hint

**关键方法**:
```python
async def describe_image_b64(
    self, 
    image_b64: str, 
    mime_type: str = "image/png",
    prompt: str | None = None,
) -> str  # raises VisionDescriptionError on failure
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

**非 Web 渠道入站**：`preprocess_inbound_multimodal_query()` 对 Channel/Cron/Voice/Kanban 等多模态 query 复用相同降级逻辑；Channel 侧通过 `ProgressUpdate(analyzing_image)` 反馈进度。

### 3. VisionFallbackProcessor (Harness Pipeline)

**位置**: `myrm_agent_harness/agent/context_management/pipeline/processors/vision_fallback_processor.py`

**职责**:
- 在 `MediaFilterProcessor` 之前，将 HumanMessage / ToolMessage 内的图像块（base64、`/api/media/...` URL、HTTP(S)、`file://`）转为 `[Image Analysis]` 文本
- 非 base64 引用通过 `resolve_image_reference_to_data_url()` 解析；业务层注入 `file_content_reader`（`files_service.get_content`）直读上传文件，HTTP loopback 仅作 fallback（`PORT` env，默认 8080）
- `apply_vision_fallback_to_messages()` 同时供 `stream_recovery_oneshot.py` 在 `MEDIA_REJECTED` 时先尝试降级再 strip
- 同条 message 内 text + image 并存时，优先用同条 text 作为 prompt；ToolMessage 优先取相邻 AIMessage 最后一段（assistant hint），其次取相邻 HumanMessage 用户文本；hint 通过 `build_vision_prompt()` 注入三段式 prompt

**配置注入**：各 ExecutionSurface 经 `extract_vision_fallback_model_config()` 解析 `defaultModelConfig.visionFallbackModel` 并写入 `GeneralAgentParams.vision_fallback_model_cfg` → harness `merged_context`。`file_content_reader` 由 server `GeneralAgent` / `create_context_pipeline_middleware` 注入。

### 4. Vision Health Check (Settings)

**API**: `POST /api/v1/config/vision-health` — 对 1×1 PNG 调用 `describe_image_b64` 探活 auxiliary 模型（连通性探测，不代表复杂图片分析能力）。失败时返回 `model` 与 `base_url`，供 Settings 排查 endpoint 误配。

**Frontend**: Settings → AI Core → Vision Fallback →「Test vision chain / 测试视觉链路」按钮（`DefaultModelSection.tsx` + `checkVisionFallbackHealth()`）。失败态展示模型名与接口地址（`settings.defaultModel` namespace · en/zh）。当主模型不支持视觉且未配置 `visionFallbackModel.primary` 时，展示「Use this model / 使用此模型」一键推荐卡片（`visionCapability.ts` 扫描已启用 Provider 中首个 `supports_vision` 模型，写入配置后走现有 failover 链）。聊天 attach/upload 在缺少视觉能力时通过 `visionConfigGap.ts` 弹出带「Go to Settings / 前往设置」的 toast，深链至 `/settings/models?sub=default`。

### 5. Frontend Status Display

**MessageBox Component** (`myrm-agent-frontend/src/components/ui/message-box/MessageBox.tsx`):
- 检查 `message.mediaAnalysisStatus`（统一字段支持 `analyzing_image` / `analyzing_video`）
- 渲染精美的状态指示器（渐变背景 + 旋转动画 + i18n 文本）

**messageStreamHandler** (`myrm-agent-frontend/src/store/chat/messageStreamHandler.ts`):
- 监听 SSE 事件 `type: "status"` + `step_key: "analyzing_image" | "analyzing_video"`
- 设置/清除 message 的 `mediaAnalysisStatus` 字段
- 读取 `vision_backend` 徽章（`vlm` / `frame` / `native_video`）并在 `MessageBox` 展示

### 6. Agent Vision Toolkit (Harness EXTENDED)

**位置**: `myrm_agent_harness/toolkits/llms/vision/vision_agent_tools.py`

**工具**:
- `vision_semantic_tool` — together / ground / region / ocr（VLM 链 + 末级 OCR tier）
- `vision_geometry_tool` — pixel_diff / crop

**挂载**: `ToolLayer.EXTENDED` · prebuilt skill `vision-toolkit` · 每 turn 语义工具默认最多 3 次调用

**Server 注入**: `GeneralAgentParams.video_fallback_model_cfgs` + `vision_fallback_model_cfgs` → agent runtime context → `file_read_tool` / chat 预处理；`create_vision_agent_tools` 仅消费 vision 槽（图像语义工具）

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
    },
    "videoFallbackModel": {
      "providerId": "google",
      "model": "gemini-2.5-flash"
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

### 3. 错误处理 — Fail-Closed 架构

`VisionFallbackEngine` 失败时 raise `VisionDescriptionError`，调用方按各自策略处理：

| 调用方 | 策略 |
|-------|------|
| `VisionFallbackProcessor` (harness pipeline) | catch → 保留原始 image block，由后续 `MediaFilterProcessor` strip |
| `chat_utils._process_image_item` (server) | catch → 返回固定无敏感信息文本 `[Image could not be analyzed]`，详细错误保留在 logger |
| `sticker_vision.py` | catch → 返回 None，跳过该贴纸描述 |
| `file_read_handlers.py` | catch → 返回固定无敏感信息文本，详细错误保留在 logger |

## 容量型 Provider Failover 链

当辅助视觉 provider 返回 billing / rate-limit / overloaded / timeout 等容量型错误时，`VisionFallbackEngine` 按有序配置链切换下一 provider（413 payload 过大仍在当前 provider 上 Reactive Resize，不切换）。`AUTH_PERMANENT` 与 `MODEL_NOT_FOUND` 不触发链切换，避免无效重试。

**链顺序（Server `resolve_vision_fallback_chain_for_agent`）**：
1. `defaultModelConfig.visionFallbackModel` primary
2. 同 slot 的 `fallback`（若 WebUI 已配置）
3. 主 Agent 模型（仅当 `supports_vision=true` 且与前面 dedupe）

**Context 字段**：`vision_fallback_model_cfgs`（完整链）+ `vision_fallback_model_cfg`（链首，兼容旧调用方）。

**Health check**：`POST /config/vision-health` 使用完整 `VisionFallbackEngine` 探测；若链首失败会容量 failover。响应 `model` 为配置 primary，`resolved_model` 为实际成功 provider（与 primary 不同时返回）。引擎 raise `VisionDescriptionError` 时判定为 unhealthy。

## 测试覆盖

### Harness Pipeline Test

**文件**: `myrm-agent-harness/tests/agent/context_management/test_vision_fallback_processor.py`

**验证点**:
- ✅ text-only 主模型 + cfg 时转换 base64 image block
- ✅ ToolMessage 使用相邻 HumanMessage text 作为 prompt
- ✅ `VisionFallbackProcessor` 记录 `vision_fallback` operation

### Backend API Test

**工具**: `httpx` 直接调用 `/api/v1/agents/agent-stream`

**验证点**:
- ✅ SSE `analyzing_image` 事件
- ✅ SSE `analyzing_image_clear` 事件
- ✅ Vision fallback 逻辑触发

### Backend API stream test (TestClient)

**工具**: FastAPI TestClient + agent-stream SSE

**文件**: `myrm-agent-server/tests/api/agent/test_vision_fallback.py`

**验证点**:
- ✅ SSE `step_key: analyzing_image` 事件
- ✅ SSE `step_key: analyzing_image_clear` 事件
- ✅ Vision fallback 逻辑触发

### chat_utils 模块测试

**文件**: `myrm-agent-server/tests/core/utils/test_chat_utils_vision.py`

**验证点**:
- ✅ `VisionFallbackEngine` / `VideoAnalysisEngine` import 自 `toolkits.llms.vision`
- ✅ MD5 cache 命中、SSE bus 发布、supports_vision 直传路径
- ✅ `preprocess_inbound_multimodal_query` 非 Web 入站预处理
- ✅ `extract_vision_fallback_model_config` SSOT 解析
- ✅ `build_vision_fallback_engine_from_providers` wiki / sticker / health 非 Agent 路径
- ✅ `should_vision_capacity_failover` 排除 AUTH / MODEL_NOT_FOUND（`test_fallback_engine.py`）

## 当前能力

1. 多图/视频并发分析（asyncio.gather）
2. MD5 hash 字典缓存（避免重复分析）
3. 视频帧提取（ffmpeg 场景检测 + 均匀采样降级）
4. 图片自动压缩（超尺寸自适应）
5. 视频大小限制（100MB）和格式验证

## 参考资料

- **LiteLLM Vision API**: https://docs.litellm.ai/docs/vision
- **SSE (Server-Sent Events)**: https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events
- **Playwright E2E Testing**: https://playwright.dev/python/

