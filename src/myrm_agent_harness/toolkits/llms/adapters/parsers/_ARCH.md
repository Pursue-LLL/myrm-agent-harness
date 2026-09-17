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
| glm_xml.py | Core | GLM `reasoning_content` tool_call tag parsing. | ✅ |
| qwen_xml_json.py | Core | Qwen XML-wrapped JSON tool call parsing. | ✅ |
| deepseek_inline.py | Core | DeepSeek inline tool call parsing. | ✅ |
| deepseek_dsml.py | Core | DeepSeek DSML-prefixed tool call parsing (the special-token wrapper around DSML tool calls). | ✅ |
| leaked_json.py | Core | Leaked raw JSON tool calls emitted as plain text (Gemini / Llama style). | ✅ |
| json_scanner.py | Core | Code-block and JSON boundary scanning helpers shared by the JSON-based parsers. | ✅ |
| text_utils.py | Core | XML tag cleaning and HTML entity decoding for tool-call text. | ✅ |

## POS
Format-conversion detail layer. The stable import surface is `tool_call_parsers`; no module outside this package imports the parsers directly.
