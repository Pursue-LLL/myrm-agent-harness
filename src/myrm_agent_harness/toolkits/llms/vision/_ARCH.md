# vision 模块架构


---

## 架构概述

视觉能力工具集模块，负责提供多模态相关的处理能力：
- **图像降级路由**：为不支持视觉的主模型提供图像自适应降级（Text-Mode Vision Fallback）
- **视频分析**：双策略视频理解引擎（直传 + ffmpeg 帧提取降级）

详细设计请参考 [VISION_SYSTEM_DESIGN.md](VISION_SYSTEM_DESIGN.md)

---

## 文件清单

| 文件 | 地位 | 职责 | I/O/P |
|-----|------|------|-------|
| `fallback_engine.py` | 核心 | 提供 `VisionFallbackEngine`：使用辅助视觉模型将图像转换为文本描述，支持过大图片自适应降级压缩。 | ✅ |
| `video_analysis_engine.py` | 核心 | 提供 `VideoAnalysisEngine`：视频分析引擎，双策略（支持视频的模型直传 + ffmpeg 帧提取降级）。 | ✅ |

---

## 架构定位

LLM 多模态**理解**层（与同级 `llms/image/` 生成、`llms/video/` 生成对称），位于 `toolkits/llms/vision/`。

## 依赖关系

- **内部**：`myrm_agent_harness.core.config.llm`、`myrm_agent_harness.toolkits.llms.core.llm`、`myrm_agent_harness.utils.media.image_compressor`
- **被依赖**：`myrm_agent_harness.agent.meta_tools.file_ops.file_read_tool`、`myrm-agent-server/app/core/utils/chat_utils.py`、`myrm-agent-server/app/channels/media/sticker_vision.py`
