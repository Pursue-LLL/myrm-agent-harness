# processing/

## Overview
Post-fetch content processing: HTML to Markdown, pruning, sanitization, URL normalization, spill, anti-bot, binary routing.

## File Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Re-exports ContentPipeline | ✅ |
| pipeline.py | Core | ContentPipeline — HTML/JSON/XML to Markdown | ✅ |
| content_sanitize.py | Util | Strip base64 blobs from markdown | ✅ |
| content_pruning.py | Util | Boilerplate/noise pruning | ✅ |
| html_to_markdown.py | Util | HTML to Markdown conversion | ✅ |
| markdown_generator.py | Util | Markdown document generation | ✅ |
| url_normalizer.py | Util | URL normalization for dedup | ✅ |
| spill.py | Util | UECD spill for large pages | ✅ |
| antibot_detector.py | Util | Anti-bot detection heuristics | ✅ |
| binary_router.py | Util | Binary content type routing | ✅ |

## Dependencies

- `fetchers.protocols`, `utils.text_cleaner`
