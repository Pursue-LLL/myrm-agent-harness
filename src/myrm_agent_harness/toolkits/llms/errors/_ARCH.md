# errors/

## Overview
LLM error processing layer: three-tier error classification, fault-tolerant calls, and standardized exception handling.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | LLM error processing layer: three-tier error classification, fault-tolerant calls, and standardized  | — |
| classifier.py | Core | LLM error classifier for failover decisions (incl. multi-source structured error code & type extraction in normalize_provider_error preventing aggregator message-masking escapes, is_quota_exhausted and source-level FailoverReason.BILLING prioritization for fast failover on irreversible quota depletion avoiding 429 retry loops, multi-WAF challenge detection with AWS WAF/Akamai/CloudFront signatures, HTML 403 challenge circuit breaker mapping to CHALLENGE_BLOCKED to prevent pool exhaustion, PROVIDER_POLICY_BLOCKED priority classification for Anthropic/aggregator guardrail & subscription policy blocks, DUPLICATE_TOOL_USE_ID, MEDIA_REJECTED multimodal rejection, distributor no-available-channel → MODEL_NOT_FOUND before generic overloaded, OpenRouter tool-use-not-supported → MODEL_NOT_FOUND, is_payload_overflow for 400/413 HTTP payload too large error detection, transient-TLS transport rule → TIMEOUT (Bun "unknown certificate verification error" mislabel / SSLEOFError / BrokenPipe — interrupted handshake with no certificate verdict) with hard-TLS blacklist → AUTH_PERMANENT fail-fast (self-signed / local issuer / first certificate / altname / expired / basicConstraints). Anthropic unified rejected quota windows (typed headers, `5h`/`7d` buckets; never the `overage` spend pool) classify as BILLING; `usage_limit_reached` / `enforced_spend_limit_reached` codes count as quota exhaustion. | ✅ |
| error_types.py | Config | Three-layer error classification system. Layer 1: recoverability, Layer 2: concrete types, Layer 3:  | ✅ |
| exceptions.py | Core | Standardized LLM exceptions for the Harness framework (MyrmLLMError, EgressChallengeBlockedError). | ✅ |
| output_limit.py | Core | `parse_output_limit()` / `OutputLimit`: reads the largest `max_tokens` a provider printed when it rejected a request, tagged as the model's own ceiling or as the remainder of the context window. Recognises the recorded wordings of DashScope, DeepSeek, Azure/OpenAI, Anthropic, OpenRouter, Volcengine Ark, Groq, OpenAI-compatible gateways, LM Studio and vLLM; any other rejection yields None, so callers keep their existing failure behaviour. | ✅ |
| provider_window/ | Subpackage | Typed "when may I retry" fact extracted once from an LLM exception (Anthropic unified rejected windows > Codex/OpenAI body > Retry-After > message text) and consumed by stream recovery, credential cooldown and diagnostics. See `provider_window/_ARCH.md`. | ✅ |
| resilient.py | Core | Resilient LLM call with automatic failover. | ✅ |
| `classifier_patterns.py` | Core | Provider error-message patterns used by the LLM failure classifier. — 限额/过载/计费/鉴权/超时/TLS/溢出/策略/WAF 等预编译模式与关键词表 | ✅ |
| `retry_after.py` | Core | ``Retry-After`` extraction from provider HTTP exceptions. — extract_retry_after(): 从 HTTP 响应头读取正数秒数，取不到返回 None | ✅ |
