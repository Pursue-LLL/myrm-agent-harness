# errors/

## Overview
LLM error processing layer: three-tier error classification, fault-tolerant calls, and standardized exception handling.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | LLM error processing layer: three-tier error classification, fault-tolerant calls, and standardized  | — |
| classifier.py | Core | LLM error classifier for failover decisions (incl. multi-WAF challenge detection with AWS WAF/Akamai/CloudFront signatures, HTML 403 challenge circuit breaker mapping to CHALLENGE_BLOCKED to prevent pool exhaustion, PROVIDER_POLICY_BLOCKED priority classification for Anthropic/aggregator guardrail & subscription policy blocks, DUPLICATE_TOOL_USE_ID, MEDIA_REJECTED multimodal rejection, distributor no-available-channel → MODEL_NOT_FOUND before generic overloaded, OpenRouter tool-use-not-supported → MODEL_NOT_FOUND, is_payload_overflow for 400/413 HTTP payload too large error detection, transient-TLS transport rule → TIMEOUT (Bun "unknown certificate verification error" mislabel / SSLEOFError / BrokenPipe — interrupted handshake with no certificate verdict) with hard-TLS blacklist → AUTH_PERMANENT fail-fast (self-signed / local issuer / first certificate / altname / expired / basicConstraints). Also provides extract_retry_after() for Retry-After header parsing. | ✅ |
| error_types.py | Config | Three-layer error classification system. Layer 1: recoverability, Layer 2: concrete types, Layer 3:  | ✅ |
| exceptions.py | Core | Standardized LLM exceptions for the Harness framework (MyrmLLMError, EgressChallengeBlockedError). | ✅ |
| output_limit.py | Core | `parse_output_limit()` / `OutputLimit`: reads the largest `max_tokens` a provider printed when it rejected a request, tagged as the model's own ceiling or as the remainder of the context window. Recognises the recorded wordings of DashScope, DeepSeek, Azure/OpenAI, Anthropic, OpenRouter, Volcengine Ark, Groq, OpenAI-compatible gateways, LM Studio and vLLM; any other rejection yields None, so callers keep their existing failure behaviour. | ✅ |
| resilient.py | Core | Resilient LLM call with automatic failover. | ✅ |
