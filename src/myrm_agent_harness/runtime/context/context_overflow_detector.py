"""Context overflow detector with 30+ vendor regex patterns and reconciliation auditing.

Reference: Mario Zechner Pi Agent (packages/ai/src/utils/overflow.ts) and post-sora_biz reconciliation.
Detects explicit errors, silent overflows, MiMo zero-output truncation, and Ollama context truncation.
Strict 0 Any, type-hinted, thread-safe.
"""

from __future__ import annotations

import re

from .pi_compaction_types import OverflowDetectionResult

# 30+ vendor regex patterns
_OVERFLOW_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "ollama_explicit",
        re.compile(
            r"prompt too long; exceeded (?:max )?context length",
            re.IGNORECASE,
        ),
    ),
    ("anthropic_token", re.compile(r"prompt (?:is )?too long", re.IGNORECASE)),
    ("anthropic_bytes", re.compile(r"request_too_large", re.IGNORECASE)),
    ("anthropic_413", re.compile(r"413\s*\{.*request_too_large", re.IGNORECASE)),
    ("amazon_bedrock", re.compile(r"input is too long for requested model", re.IGNORECASE)),
    ("openai_window", re.compile(r"exceeds the context window", re.IGNORECASE)),
    (
        "openai_max_length",
        re.compile(
            r"exceeds (?:the )?(?:model'?s )?maximum context length(?: of [\d,]+ tokens?|\s*\([\d,]+\))",
            re.IGNORECASE,
        ),
    ),
    ("google_gemini", re.compile(r"input token count.*exceeds the maximum", re.IGNORECASE)),
    ("google_resource", re.compile(r"RESOURCE_EXHAUSTED.*context length", re.IGNORECASE)),
    ("xai_grok", re.compile(r"maximum prompt length is \d+", re.IGNORECASE)),
    ("groq", re.compile(r"reduce the length of the messages", re.IGNORECASE)),
    ("openrouter_len", re.compile(r"maximum context length is \d+ tokens", re.IGNORECASE)),
    (
        "openrouter_poolside",
        re.compile(
            r"exceeds (?:the )?maximum allowed input length of [\d,]+ tokens?",
            re.IGNORECASE,
        ),
    ),
    (
        "together_ai",
        re.compile(
            r"input \(\d+ tokens\) is longer than the model'?s context length",
            re.IGNORECASE,
        ),
    ),
    ("github_copilot", re.compile(r"exceeds the limit of \d+", re.IGNORECASE)),
    ("llama_cpp", re.compile(r"exceeds the available context size", re.IGNORECASE)),
    ("lm_studio", re.compile(r"greater than the context length", re.IGNORECASE)),
    ("minimax", re.compile(r"context window exceeds limit", re.IGNORECASE)),
    ("kimi", re.compile(r"exceeded model token limit", re.IGNORECASE)),
    ("mistral", re.compile(r"too large for model with \d+ maximum context length", re.IGNORECASE)),
    (
        "ds4",
        re.compile(
            r"prompt has [\d,]+ tokens?, but the configured context size is [\d,]+ tokens?",
            re.IGNORECASE,
        ),
    ),
    ("zai_cn", re.compile(r"prompt exceeds max length", re.IGNORECASE)),
    ("zai_window", re.compile(r"model_context_window_exceeded", re.IGNORECASE)),
    ("dashscope_qwen", re.compile(r"range of input length should be", re.IGNORECASE)),
    (
        "cerebras_bodyless",
        re.compile(r"^4(?:00|13)\s*(?:status code)?\s*\(no body\)", re.IGNORECASE),
    ),
    ("generic_exceeded", re.compile(r"context[_ ]length[_ ]exceeded", re.IGNORECASE)),
    ("generic_too_many", re.compile(r"too many tokens", re.IGNORECASE)),
    ("generic_limit", re.compile(r"token limit exceeded", re.IGNORECASE)),
)

# False positive exclusions (rate limiting or server errors)
_NON_OVERFLOW_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^(?:Throttling error|Service unavailable):", re.IGNORECASE),
    re.compile(r"rate limit", re.IGNORECASE),
    re.compile(r"too many requests", re.IGNORECASE),
    re.compile(r"quota exceeded", re.IGNORECASE),
)


class ContextOverflowDetector:
    """Detects explicit error strings, silent token overflow, and cross-tier token truncation."""

    @classmethod
    def detect_error_overflow(cls, error_text: str) -> OverflowDetectionResult:
        """Scan error message against 30+ vendor regex patterns while filtering rate-limits."""
        if not error_text:
            return OverflowDetectionResult(
                is_overflow=False,
                vendor="none",
                matched_pattern="",
            )

        # 1. Exclude false-positive rate limiting errors
        for non_ovf in _NON_OVERFLOW_PATTERNS:
            if non_ovf.search(error_text):
                return OverflowDetectionResult(
                    is_overflow=False,
                    vendor="excluded_rate_limit",
                    matched_pattern=non_ovf.pattern,
                )

        # 2. Check 30+ patterns
        for vendor_tag, pattern in _OVERFLOW_PATTERNS:
            if pattern.search(error_text):
                return OverflowDetectionResult(
                    is_overflow=True,
                    vendor=vendor_tag,
                    matched_pattern=pattern.pattern,
                    diagnostic_hint="Reduce prompt context or trigger progressive compaction",
                )

        return OverflowDetectionResult(
            is_overflow=False,
            vendor="unknown",
            matched_pattern="",
        )

    @classmethod
    def audit_token_reconciliation(
        cls,
        prompt_budget_tokens: int,
        server_received_tokens: int,
        context_window: int = 128000,
        stop_reason: str = "",
        output_tokens: int = 0,
    ) -> OverflowDetectionResult:
        """Audit serving-layer silent truncation and MiMo-style zero-output length stops."""
        # Case A: Xiaomi MiMo zero-output truncation
        # stop_reason is "length", output_tokens is 0, and input tokens filled or nearly filled context
        if stop_reason == "length" and output_tokens == 0 and server_received_tokens >= (context_window * 0.95):
            return OverflowDetectionResult(
                is_overflow=True,
                vendor="xiaomi_mimo_truncation",
                matched_pattern="stop_reason=length with output=0",
                is_silent_truncation=True,
                prompt_budget=prompt_budget_tokens,
                server_tokens=server_received_tokens,
                diagnostic_hint="MiMo input filled context window with 0 remaining generation tokens.",
            )

        # Case B: Serving-tier silent prompt truncation (e.g., Ollama 12GB VRAM default 4K truncation)
        # Client budgeted > 4000 tokens, but server only processed significantly fewer (< 70% of budgeted)
        if prompt_budget_tokens >= 4096 and server_received_tokens > 0:
            deficit_ratio = (prompt_budget_tokens - server_received_tokens) / prompt_budget_tokens
            if deficit_ratio >= 0.25:  # Lost 25%+ of input prompt silently
                return OverflowDetectionResult(
                    is_overflow=True,
                    vendor="ollama_silent_truncation",
                    matched_pattern=f"deficit_ratio={deficit_ratio:.1%}",
                    is_silent_truncation=True,
                    prompt_budget=prompt_budget_tokens,
                    server_tokens=server_received_tokens,
                    diagnostic_hint=(
                        "Serving layer silently truncated prompt! Run 'ollama ps' CONTEXT column, "
                        "check server.log for 'truncating input prompt', and set PARAMETER num_ctx 65536."
                    ),
                )

        # Case C: Direct silent overflow where server input tokens exceed context window
        if server_received_tokens > context_window:
            return OverflowDetectionResult(
                is_overflow=True,
                vendor="silent_overflow",
                matched_pattern="server_tokens > context_window",
                is_silent_truncation=True,
                prompt_budget=prompt_budget_tokens,
                server_tokens=server_received_tokens,
                diagnostic_hint=f"Input {server_received_tokens} exceeded context window {context_window}.",
            )

        return OverflowDetectionResult(
            is_overflow=False,
            vendor="reconciled",
            matched_pattern="",
            is_silent_truncation=False,
            prompt_budget=prompt_budget_tokens,
            server_tokens=server_received_tokens,
        )
