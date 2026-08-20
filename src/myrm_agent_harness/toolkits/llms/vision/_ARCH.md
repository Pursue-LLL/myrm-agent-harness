# vision 模块架构


---

## 架构概述

视觉能力工具集模块，负责提供多模态相关的处理能力：
- **图像降级路由**：为不支持视觉的主模型提供图像自适应降级（Text-Mode Vision Fallback）
- **视频分析**：双策略视频理解引擎（直传 + ffmpeg 帧提取降级）
- **多模态文件输入支持**：为 `file_read_tool` 等文件工具提供统一多模态转换与降级基础设施

详细设计请参考 [VISION_SYSTEM.md](VISION_SYSTEM.md)

---

## 文件清单

| 文件 | 地位 | 职责 | I/O/P |
|-----|------|------|-------|
| `__init__.py` | Package | Vision toolkit package exports | — |
| `types.py` | 核心 | `VisionResult` / `VisionBackendKind` / `VisionCacheKey` 等 SSOT 类型 | ✅ |
| `cache.py` | 核心 | prompt-aware vision cache key + in-memory store | ✅ |
| `fallback_engine.py` | 核心 | `VisionFallbackEngine` / `VisionDescriptionError` / fail-closed VLM 链。模型装配 temperature 语义：顶层 `cfg.temperature` 优先 → `model_kwargs.temperature` 其次 → 默认 0.1 兜底，避免具名参数冲突 | ✅ |
| `video_analysis_engine.py` | 核心 | `VideoAnalysisEngine`：原生视频直传 + ffmpeg 帧提取降级。temperature 装配语义与 `fallback_engine` 一致（顶层优先 → model_kwargs 其次 → 默认 0.1） | ✅ |
| `transcode.py` | 辅助 | H.264 pre-upload transcode + temp path cleanup | ✅ |
| `ocr_tier.py` | 辅助 | 末级 PaddleOCR（经 sandbox `executor.read_file_bytes`） | ✅ |

---

## 架构定位

LLM 多模态**理解**层（与同级 `llms/image/` 生成、`llms/video/` 生成对称），位于 `toolkits/llms/vision/`。

Server 侧媒体路由 SSOT：`myrm-agent-server/app/core/vision/media_router.py`

## 依赖关系

- **内部**：`myrm_agent_harness.core.config.llm`、`myrm_agent_harness.toolkits.llms.core.llm`、`myrm_agent_harness.utils.media.image_compressor`、`myrm_agent_harness.toolkits.file_parsers.ocr`
- **被依赖**：`file_read_tool`、`chat_utils.py`、`sticker_vision.py`、`asset_index_service.py`
