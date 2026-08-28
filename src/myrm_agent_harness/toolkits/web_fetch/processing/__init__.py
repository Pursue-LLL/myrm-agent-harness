"""Content processing pipeline utilities for web fetch.

[INPUT]
- processing.pipeline (POS: HTML/JSON/XML to Markdown pipeline)
- processing.spill (POS: UECD spill wrapper for large pages)

[OUTPUT]
- Re-exports: ContentPipeline, spill helpers, markdown and sanitization utilities

[POS]
Subpackage entry for post-fetch content processing and markdown conversion.
"""

from myrm_agent_harness.toolkits.web_fetch.processing.pipeline import ContentPipeline

__all__ = ["ContentPipeline"]
