# parsers/

## Overview
Provider-specific tool-call format parsers. Each module owns one wire format; all are dispatched through the `tool_call_parsers` facade in priority order.

## File Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Re-exports the per-format parse entry points. | ✅ |
| types.py | Core | Tool-call type definitions (`FunctionCallDict`, `ToolCallDict`, `LLMResponseDict`). | ✅ |
| openai_format.py | Core | Native OpenAI `tool_calls` payload parsing. | ✅ |
| anthropic_xml.py | Core | Anthropic `<function_calls>` / `<invoke>` XML parsing. | ✅ |
| glm_xml.py | Core | GLM `reasoning_content` tool_call tag parsing. Extracts the function name before the first arg tag (GLM-4.7 may place it on the same line as the first `<arg_key>`), then repairs a single dropped `<arg_value>` open/close tag and pairs `arg_key`/`arg_value` in document order. A value whose open tag was dropped is recovered from the preceding `</arg_key>`; a value whose close tag was dropped is closed before the next key or at the matched block's end; well-formed blocks stay byte-identical, and nothing is ever shifted onto the wrong key. Every scan over model output is linear in its size: `_scan_elements` (forward-only tag finders) is the linear-time equivalent of the lazy `<tag>(.*?)</tag>` regexes, which rescan to the end of the text for each unclosed opener; a model stuck repeating a tag therefore cannot stall the event loop. | ✅ |
| qwen_xml_json.py | Core | Qwen XML-wrapped JSON tool call parsing. | ✅ |
| deepseek_inline.py | Core | DeepSeek inline tool call parsing. | ✅ |
| deepseek_dsml.py | Core | DeepSeek DSML-prefixed tool call parsing (the special-token wrapper around DSML tool calls). | ✅ |
| leaked_json.py | Core | Leaked raw JSON tool calls emitted as plain text (Gemini / Llama style). | ✅ |
| json_scanner.py | Core | Code-block and JSON boundary scanning helpers shared by the JSON-based parsers. | ✅ |
| text_utils.py | Core | XML tag cleaning and single-pass HTML entity decoding for tool-call text (one level: `&amp;lt;` → `&lt;`). Callers apply the decoder only to models known to escape (xAI Grok). | ✅ |

## POS
Format-conversion detail layer. The stable import surface is `tool_call_parsers`; no module outside this package imports the parsers directly.
