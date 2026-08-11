"""Bash tool capability domain: description, formatting, exit semantics, multimodal.

See _ARCH.md for file index.
"""

from .formatting import BASH_OUTPUT_MAX_CHARS
from .tool_description import TOOL_DESCRIPTION

__all__ = ["BASH_OUTPUT_MAX_CHARS", "TOOL_DESCRIPTION"]
