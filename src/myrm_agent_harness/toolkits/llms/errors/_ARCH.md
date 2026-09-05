# errors/

## Overview
LLM error processing layer: three-tier error classification, fault-tolerant calls, and standardized exception handling.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | LLM error processing layer: three-tier error classification, fault-tolerant calls, and standardized  | — |
| classifier.py | Core | LLM error classifier for failover decisions (incl. PROVIDER_POLICY_BLOCKED priority classification for Anthropic/aggregator guardrail & subscription policy blocks, DUPLICATE_TOOL_USE_ID, MEDIA_REJECTED multimodal rejection, distributor no-available-channel → MODEL_NOT_FOUND before generic overloaded, OpenRouter tool-use-not-supported → MODEL_NOT_FOUND, is_payload_overflow for 400/413 HTTP payload too large error detection). Also provides extract_retry_after() for Retry-After header parsing and parse_available_output_tokens_from_error() for 5-format output-cap token extraction (Anthropic/OpenRouter/LM Studio/vLLM/DashScope). | ✅ |
| error_types.py | Config | Three-layer error classification system. Layer 1: recoverability, Layer 2: concrete types, Layer 3:  | ✅ |
| exceptions.py | Core | Standardized LLM exceptions for the Harness framework (MyrmLLMError). | ✅ |
| resilient.py | Core | Resilient LLM call with automatic failover. | ✅ |
