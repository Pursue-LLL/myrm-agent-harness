"""Utility functions module.

提供路径处理、文件操作、行尾处理、图片多模态读取、PDF 多模态读取等工具函数。
"""

from .file_utils import parse_path_with_range
from .image_reader import is_image_path, read_image_as_content_blocks
from .line_endings import detect_line_ending, normalize_line_endings
from .path_utils import resolve_file_id_path
from .pdf_reader import is_pdf_path, read_pdf_as_content_blocks

__all__ = [
    "detect_line_ending",
    "is_image_path",
    "is_pdf_path",
    "normalize_line_endings",
    "parse_path_with_range",
    "read_image_as_content_blocks",
    "read_pdf_as_content_blocks",
    "resolve_file_id_path",
]
