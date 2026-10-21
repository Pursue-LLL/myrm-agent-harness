"""Vision Toolkits.

[INPUT]
- 图像/视频输入（缓存、回退模型配置）

[OUTPUT]
- VisionCacheStore: 视觉结果缓存
- VisionFallbackEngine: 视觉回退引擎（视频双槽位）
- create_vision_fallback_engine(): 工厂函数

[POS]
Vision capability layer — caches vision results and orchestrates fallback chains
for images and videos (including dual-slot video parity).
"""

from .cache import VisionCacheStore, build_cache_key, get_vision_cache_store
from .fallback_engine import (
    VisionDescriptionError,
    VisionFallbackEngine,
    create_vision_fallback_engine,
    pick_video_fallback_model_cfgs,
    resolve_vision_fallback_llm_configs,
)
from .ocr_tier import OcrTierEngine
from .transcode import has_ffmpeg, transcode_video_h264
from .types import (
    VisionBackendKind,
    VisionCacheKey,
    VisionResult,
)
from .video_analysis_engine import VideoAnalysisEngine

__all__ = [
    "OcrTierEngine",
    "VideoAnalysisEngine",
    "VisionBackendKind",
    "VisionCacheKey",
    "VisionCacheStore",
    "VisionDescriptionError",
    "VisionFallbackEngine",
    "VisionResult",
    "build_cache_key",
    "create_vision_fallback_engine",
    "get_vision_cache_store",
    "has_ffmpeg",
    "pick_video_fallback_model_cfgs",
    "resolve_vision_fallback_llm_configs",
    "transcode_video_h264",
]
