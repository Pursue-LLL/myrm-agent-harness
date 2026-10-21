"""Provider error-message patterns used by the LLM failure classifier.

Every regex here was compiled once at import time for the classifier's multi-probe
pipeline; they are pure data, so they live apart from the classification logic that
consumes them.

[INPUT]
- re (POS: 正则编译)

[OUTPUT]
- 限额/过载/计费/鉴权/超时/TLS/溢出/策略/WAF 等预编译模式与关键词表

[POS]
Pattern table for ``classifier.py``. Kept in its own module so the classifier reads as
a decision pipeline rather than a wall of regexes, and so a pattern can be audited on
its own. The ``_CLOUDFLARE_CHALLENGE_RE`` alias keeps the older call-site name.
"""

from __future__ import annotations

import re

# ============================================================================
# Rate limit / overload
# ============================================================================

_RATE_LIMIT_RE = re.compile(
    r"\btpm\b|tokens per minute|rate.?limit|too many requests|\b429\b|throttl"
    r"|resource.?exhausted|requests per (?:minute|hour|day)"
    r"|rate increased too quickly|too many concurrent requests"
    r"|servicequotaexceededexception",
    re.IGNORECASE,
)

_OVERLOADED_RE = re.compile(
    r"overloaded(?:_error)?|high.?demand|capacity.?(?:exceeded|full)"
    r"|\b529\b|service.?unavailable|\b502\b|\b503\b|\b504\b",
    re.IGNORECASE,
)

_OVERLOADED_503_RE = re.compile(
    r"(?:service.?unavailable|503).*(?:overload|capacity|high.?demand)"
    r"|(?:overload|capacity|high.?demand).*(?:service.?unavailable|503)",
    re.IGNORECASE,
)

# ============================================================================
# Billing / auth / timeout
# ============================================================================

_BILLING_RE = re.compile(
    r"billing|insufficient.?(?:balance|funds|credits|quota)|payment.?required|exceeded.?(?:plan|budget|quota)"
    r"|credit.?balance|\b402\b|run out of credits|used all available credits|grok subscription"
    r"|余额不足|额度不足|请充值|欠费|无可用资源包|account is deactivated|top up your credits",
    re.IGNORECASE,
)

_AUTH_RE = re.compile(
    r"invalid.?api.?key|incorrect api key|unauthorized|\b401\b|\b403\b"
    r"|authentication|access.?denied|forbidden|permission.?(?:error|denied)"
    r"|api.?key.?(?:revoked|invalid|deactivated|expired)|token.?(?:has )?expired",
    re.IGNORECASE,
)

_TIMEOUT_RE = re.compile(
    r"\btimeout\b|timed.?out|deadline.?exceeded|connection.?(?:error|reset|refused)"
    r"|network.?(?:error|request failed)|fetch.?failed|socket.?hang.?up"
    r"|\b499\b"
    r"|server disconnected|unexpected eof|connection was closed",
    re.IGNORECASE,
)

# Permanent TLS failure: the certificate/chain itself is rejected (fail-fast,
# never retried). Checked AFTER the transient-transport rule so that weak-
# network handshakes interrupted before any certificate verdict stay retryable.
_TLS_HARD_RE = re.compile(
    r"self.?signed|unable to get local issuer"
    r"|unable to verify the first certificate"
    r"|hostname (?:mismatch|doesn.?t match)|err_tls_cert_altname_invalid|altname"
    r"|certificate (?:has )?expired|expired certificate"
    r"|basic.?constraints|not marked critical"
    r"|certificate verify failed",
    re.IGNORECASE,
)

# Transient TLS transport trace: SSL/TLS/handshake wording with NO hard
# signal. Covers Bun's mislabeled "unknown certificate verification error"
# (reset mid-handshake, no certificate ever rejected) and Python SSLEOFError /
# BrokenPipeError wordings that _TIMEOUT_RE misses ("unexpected_eof" with
# underscores, "eof occurred in violation of protocol", "broken pipe").
_TLS_TRANSPORT_RE = re.compile(
    r"\bssl\b|\btls\b|handshake"
    r"|unknown[ _]certificate[ _]verification|certificate verification error"
    r"|cert\.? ?verify|ssl routines"
    r"|unexpected.?eof|eof occurred in violation of protocol|broken pipe"
    r"|wrong version number|bad record|decryption failed"
    r"|ssl3_|tlsv1",
    re.IGNORECASE,
)

# ============================================================================
# Context / payload overflow
# ============================================================================

_OVERFLOW_EXACT_RE = re.compile(
    r"|".join(
        [
            r"request_too_large",
            r"context[_ ]?length[_ ]?exceeded",
            r"maximum context length",
            r"(?:model[_ ]?)?context[_ ]?window[_ ]?exceeded",
            r"exceeds?[_ ](?:the[_ ])?model.?s?[_ ]?(?:maximum[_ ])?context",
            r"prompt is too long",
            r"model token limit",
            r"exceed context limit",
            r"request exceeds the maximum size",
            r"request size exceeds",
            r"exceeds the max_model_len",
            r"max_model_len",
            r"maximum model length",
            r"slot context",
            r"n_ctx_slot",
            r"exceeds the maximum number of input tokens",
            r"token.?limit.?exceeded",
            r"prompt exceeds max length",
            r"tokens in request more than max tokens allowed",
            r"total message size.*exceeds limit",
            r"context size has been exceeded",
            r"available context size",
            r"input tokens exceed",
        ]
    ),
    re.IGNORECASE,
)

_OVERFLOW_COMPOUND_CHECKS: list[tuple[re.Pattern[str], ...]] = [
    (
        re.compile(r"max_tokens", re.IGNORECASE),
        re.compile(r"exceed", re.IGNORECASE),
        re.compile(r"context", re.IGNORECASE),
    ),
    (
        re.compile(r"input length", re.IGNORECASE),
        re.compile(r"exceed", re.IGNORECASE),
        re.compile(r"context", re.IGNORECASE),
    ),
    (re.compile(r"413", re.IGNORECASE), re.compile(r"too large", re.IGNORECASE)),
]

_OVERFLOW_CN_KEYWORDS = (
    "上下文过长",
    "上下文超出",
    "上下文长度超",
    "超出最大上下文",
    "请压缩上下文",
)

_PAYLOAD_TOO_LARGE_RE = re.compile(
    r"payload too large"
    r"|request entity too large"
    r"|request body too large"
    r"|client intended to send too large body"
    r"|body size exceeds"
    r"|payload size exceeds"
    r"|payload exceeds"
    r"|request body exceeds"
    r"|request size exceeds"
    r"|entity too large"
    r"|client_max_body_size"
    r"|exceeded the maximum request size"
    r"|exceeds.+maximum.+request.+size"
    r"|maximum payload size exceeded"
    r"|body exceeds size limit"
    r"|request exceeds maximum.+size",
    re.IGNORECASE,
)

# ============================================================================
# Provider / model semantics
# ============================================================================

_LITELLM_INIT_BUG_RE = re.compile(
    r"BadRequestError\.__init__\(\).*missing.*required positional argument",
    re.IGNORECASE,
)

_PROVIDER_FORMAT_400_RE = re.compile(
    r"must be in JSON format|InvalidParameter.*(?:function|arguments)"
    r"|schema validation error|invalid format|invalid json format|valid JSON",
    re.IGNORECASE,
)

_MODEL_NOT_FOUND_RE = re.compile(
    r"is not a valid model|invalid model|model not found|model_not_found"
    r"|does not exist|no such model|unknown model|unsupported model"
    r"|no endpoints found that support tool use"
    r"|no available channel(?: for model)?",
    re.IGNORECASE,
)

_USAGE_LIMIT_TRANSIENT_SIGNALS = [
    "try again",
    "retry",
    "resets at",
    "reset in",
    "wait",
    "requests remaining",
    "periodic",
    "window",
]

_USAGE_LIMIT_PATTERNS = ["usage limit", "quota", "limit exceeded", "key limit exceeded"]

_SAFETY_BLOCK_RE = re.compile(
    r"content_policy_violation|violating our usage policy|safety system"
    r"|content filtered|responsible ai policy|safety block",
    re.IGNORECASE,
)

_THINKING_SIGNATURE_RE = re.compile(
    r"signature.*thinking|thinking.*signature",
    re.IGNORECASE,
)

_REASONING_MANDATORY_RE = re.compile(
    r"(?:reasoning|thinking).*?(?:mandatory|cannot be disabled|required|must be enabled|cannot be omitted)"
    r"|cannot disable (?:reasoning|thinking)"
    r"|reasoning_effort.*?(?:not supported|unrecognized|invalid|does not support|required|must not be disabled)"
    r"|thinking_budget.*?(?:required|must be provided|invalid)"
    r"|unsupported.*?(?:reasoning|thinking)",
    re.IGNORECASE,
)

_DUPLICATE_TOOL_USE_ID_RE = re.compile(
    r"tool_use.{0,40}(?:unique|duplicate|duplicat|must be)"
    r"|duplicate.{0,40}tool_use"
    r"|tool_call_id.{0,40}(?:unique|duplicate|duplicat|must be)"
    r"|(?:unique|duplicate).{0,40}tool_call_id"
    r"|messages\.\d+\.tool_calls\.\d+\.id",
    re.IGNORECASE,
)

# ============================================================================
# Multimodal / long-context tier
# ============================================================================

_IMAGE_TOO_LARGE_RE = re.compile(
    r"image exceeds|image.{0,6}too.{0,3}large|image_too_large|image size exceeds"
    r"|exceeds.+per.?image.+limit"
    r"|image.?dimensions?.+exceed|dimensions?.+exceed.+(?:maximum|max|limit|allowed)"
    r"|exceeds.+(?:maximum|max).+(?:allowed )?size.+\d+",
    re.IGNORECASE,
)

_LONG_CONTEXT_TIER_RE = re.compile(
    r"extra usage.+(?:required|needed).+long context",
    re.IGNORECASE,
)

_MEDIA_REJECTED_RE = re.compile(
    r"does not support (?:image|vision|multimodal|media)"
    r"|(?:image|vision|multimodal|media).+(?:not supported|not available|unsupported)"
    r"|cannot process (?:image|media|multimodal)"
    r"|model does not have vision"
    r"|content type.+image.+not supported"
    r"|invalid content type.+image",
    re.IGNORECASE,
)

# ============================================================================
# Provider policy / WAF challenge
# ============================================================================

_PROVIDER_POLICY_BLOCKED_RE = re.compile(
    r"no endpoints available matching your (?:guardrail|data policy)"
    r"|organization has been (?:disabled|suspended|blocked)"
    r"|third[- ]party (?:client|app|application|integration|tool).*(?:not (?:permitted|allowed|supported|authorized)|disallowed|restricted)"
    r"|(?:not (?:authorized|permitted|allowed|supported)|unauthorized).*(?:third[- ]party|external|direct api)"
    r"|credential is not authorized for (?:direct )?(?:api|third[- ]party|client) access"
    r"|subscription tier does not allow (?:external|api|tool)"
    r"|claude (?:pro|max|team)? (?:subscription|account).*(?:not (?:permitted|allowed|supported)|requires? (?:extra|approved)|extra usage credits)"
    r"|(?:extra )?usage credits required"
    r"|only available (?:via|in) (?:claude code|official|claude\.ai)"
    r"|blocked by (?:provider|anthropic) policy",
    re.IGNORECASE,
)

_WAF_CHALLENGE_RE = re.compile(
    r"challenges\.cloudflare\.com"
    r"|cf-turnstile"
    r"|cf-ray"
    r"|cf_chl_opt"
    r"|just a moment\.{3}"
    r"|attention required!? \| cloudflare"
    r"|error code:? (?:1020|1015|1006|1007|1008)"
    r"|cloudflare-nginx"
    r"|challenge-platform"
    r"|verify you are human"
    r"|checking your browser before accessing"
    r"|ddos protection by cloudflare"
    r"|x-amzn-waf-action"
    r"|request blocked by (?:aws )?waf"
    r"|blocked by administrative rules"
    r"|akamaighost"
    r"|access denied.*?permission to access"
    r"|generated by cloudfront"
    r"|blocked by web application firewall"
    r"|waf block(?:ed)?"
    r"|waf challenge"
    r"|(?:ip|client) (?:address )?(?:is )?blocked"
    r"|blocked by security policy"
    r"|access denied by security"
    r"|bot (?:traffic|detection|protection|challenge)"
    r"|turnstile[-_ ]required",
    re.IGNORECASE,
)
_CLOUDFLARE_CHALLENGE_RE = _WAF_CHALLENGE_RE
