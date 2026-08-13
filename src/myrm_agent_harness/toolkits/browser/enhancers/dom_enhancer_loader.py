"""DOM Enhancer module.

Provides a script that enhances DOM by exposing React/Vue interactive elements
and injecting SPA stability detection.

[INPUT]
- dom_enhancer.js (bundled asset in same directory)

[OUTPUT]
- get_dom_enhancer_script(): Load and return the dom_enhancer.js script content.

[POS]
DOM enhancer script loader. Bundles and serves the JS enhancer to page init.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_dom_enhancer_script() -> str:
    """Load and return the dom_enhancer.js script content."""
    script_path = Path(__file__).parent / "dom_enhancer.js"
    try:
        return script_path.read_text(encoding="utf-8")
    except Exception as e:
        logger.error(f"Failed to load dom_enhancer.js: {e}")
        return ""
