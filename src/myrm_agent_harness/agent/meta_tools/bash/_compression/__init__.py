"""Bash output compression domain: semantic compressors, eviction, declarative filters.

Public symbols: :func:`compress_output`, :func:`maybe_evict_large_output`,
:data:`BASH_OUTPUT_MAX_CHARS`.
See _ARCH.md for file index.
"""

from .constants import BASH_OUTPUT_MAX_CHARS
from .output_compressor import compress_output
from .output_eviction import maybe_evict_large_output

__all__ = ["BASH_OUTPUT_MAX_CHARS", "compress_output", "maybe_evict_large_output"]
