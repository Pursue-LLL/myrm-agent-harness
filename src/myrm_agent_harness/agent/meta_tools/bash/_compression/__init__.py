"""Bash output compression domain: semantic compressors, eviction, declarative filters.

Public symbols: :func:`compress_output`, :func:`maybe_evict_large_output`.
See _ARCH.md for file index.
"""

from .output_compressor import compress_output
from .output_eviction import maybe_evict_large_output

__all__ = ["compress_output", "maybe_evict_large_output"]
