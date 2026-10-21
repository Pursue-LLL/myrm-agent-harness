"""Compile structure survey package.

[INPUT]
- .builder::build_compile_survey (POS: compile survey builder)
- .types::FAST_PATH_MAX_FOLDER_DEPTH, FAST_PATH_MAX_RAW_COUNT, CompileSessionState, CompileSurveyContext, FacetSurvey (POS: survey types and thresholds)

[OUTPUT]
- FAST_PATH_MAX_FOLDER_DEPTH, FAST_PATH_MAX_RAW_COUNT, CompileSessionState, CompileSurveyContext, FacetSurvey, build_compile_survey

[POS]
Compile Survey 编译结构测绘模块入口。在语义抽取前无 LLM 快速扫描目录刻面与切片关系。
"""

from .builder import build_compile_survey
from .types import (
    FAST_PATH_MAX_FOLDER_DEPTH,
    FAST_PATH_MAX_RAW_COUNT,
    CompileSessionState,
    CompileSurveyContext,
    FacetSurvey,
)

__all__ = [
    "FAST_PATH_MAX_FOLDER_DEPTH",
    "FAST_PATH_MAX_RAW_COUNT",
    "CompileSessionState",
    "CompileSurveyContext",
    "FacetSurvey",
    "build_compile_survey",
]
