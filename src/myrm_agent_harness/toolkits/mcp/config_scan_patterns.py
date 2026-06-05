"""MCP security scan regex patterns (static + runtime surface).

[OUTPUT]
- SECRET_REF_PREFIX, RISKY_SERVER_PATTERNS, EXFILTRATION_URL_PATTERNS
- NAME_INJECTION_PATTERNS, SENSITIVE_PATH_PATTERN, NPX_AUTO_INSTALL
- INJECTION_PATTERN_SPECS (description/instruction poisoning patterns)

[POS]
Compiled regex pattern constants for MCP static and runtime surface scanners.
"""

from __future__ import annotations

import re

SECRET_REF_PREFIX = "{{secret:"

RISKY_SERVER_PATTERNS: tuple[tuple[re.Pattern[str], str, str, str], ...] = (
    (
        re.compile(r"shell|terminal|command", re.I),
        "critical",
        "Shell/command MCP grants arbitrary execution",
        "Use an allowlist of specific commands instead of unrestricted shell access",
    ),
    (
        re.compile(r"filesystem", re.I),
        "high",
        "Filesystem MCP can read/write local files",
        "Restrict to specific directories using allowedDirectories config",
    ),
    (
        re.compile(r"puppeteer|playwright|browser", re.I),
        "high",
        "Browser automation MCP can run arbitrary JS",
        "Restrict to specific domains and disable script execution where possible",
    ),
    (
        re.compile(r"database|postgres|mysql|sqlite|mongo", re.I),
        "high",
        "Database MCP can access sensitive data",
        "Use a read-only connection and restrict to specific tables/schemas",
    ),
    (
        re.compile(r"slack|discord|email|sendgrid", re.I),
        "medium",
        "Messaging MCP can send messages to external services",
        "Restrict to specific channels and require confirmation for outbound sends",
    ),
)

EXFILTRATION_URL_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bngrok\.io\b", re.I), "ngrok tunneling service"),
    (re.compile(r"\bngrok\.app\b", re.I), "ngrok tunneling service"),
    (re.compile(r"\bwebhook\.site\b", re.I), "webhook.site data collection endpoint"),
    (re.compile(r"\brequestbin\.com\b", re.I), "RequestBin data collection endpoint"),
    (re.compile(r"\brequestcatcher\.com\b", re.I), "RequestCatcher data collection endpoint"),
    (re.compile(r"\bhookbin\.com\b", re.I), "Hookbin data collection endpoint"),
    (re.compile(r"\bpipedream\.net\b", re.I), "Pipedream webhook endpoint"),
    (re.compile(r"\bbeeceptor\.com\b", re.I), "Beeceptor mock/intercept endpoint"),
    (re.compile(r"\binteractsh\.com\b", re.I), "Interactsh out-of-band interaction server"),
    (re.compile(r"\bburpcollaborator\.net\b", re.I), "Burp Collaborator exfiltration endpoint"),
    (re.compile(r"\bcollect\?data=|/exfil|/steal|/leak\b", re.I), "URL path suggesting data exfiltration"),
)

NAME_INJECTION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"https?://", re.I),
    re.compile(r"[\n\r]"),
    # [\s_]+ matches sanitize_mcp_name_component output (spaces → underscores).
    re.compile(r"ignore[\s_]+(previous|all|prior)[\s_]+instructions?", re.I),
    re.compile(r"system[\s_]*:", re.I),
    re.compile(r"you[\s_]+are[\s_]+now", re.I),
    re.compile(
        r"(send|exfiltrate|steal|leak|extract|read|dump|collect)[\s_\-/].*(to|from|all|every)"
        r"[\s_\-/].*(https?|urls?|servers?|endpoints?|secrets?|keys?|tokens?|passwords?|credentials?|ssh|env)",
        re.I,
    ),
    re.compile(r"read[\s_].*(?:and|then)[\s_].*send", re.I),
)

SENSITIVE_PATH_PATTERN = re.compile(
    r"(~/?\.ssh|~/?\.gnupg|~/?\.kube|/etc/passwd|/etc/shadow|\.env\b|id_rsa|\.aws/credentials)",
    re.I,
)

NPX_AUTO_INSTALL = re.compile(r"^npx$|^npm exec$", re.I)

# Word-boundary separators use [\s_]+ so underscore variants match (aligned with NAME_INJECTION_PATTERNS).
INJECTION_PATTERN_SPECS: tuple[tuple[re.Pattern[str], str, str, str], ...] = (
    (
        re.compile(
            r"ignore[\s_]+(all[\s_]+)?(previous|above|prior)[\s_]+(instructions?|rules?|prompts?)",
            re.I,
        ),
        "prompt_injection",
        "critical",
        "Reject this MCP server and report the finding to your administrator",
    ),
    (
        re.compile(r"you[\s_]+are[\s_]+now[\s_]+(a|an|the)[\s_]+", re.I),
        "prompt_injection",
        "high",
        "Review server instructions manually before enabling this MCP",
    ),
    (
        re.compile(r"(system[\s_]*prompt|system[\s_]*message)[\s_]*[:=]", re.I),
        "prompt_injection",
        "high",
        "Review server instructions manually before enabling this MCP",
    ),
    (
        re.compile(r"<\s*(system|human|assistant)\s*>", re.I),
        "prompt_injection",
        "high",
        "Review server instructions manually before enabling this MCP",
    ),
    (
        re.compile(r"do[\s_]+not[\s_]+(tell|inform|mention|reveal)", re.I),
        "concealment_instruction",
        "medium",
        "Treat concealed instructions as untrusted and keep the server disabled",
    ),
    (
        re.compile(r"(curl|wget|fetch)[\s_]+https?://", re.I),
        "data_exfiltration",
        "high",
        "Remove outbound fetch instructions from tool descriptions",
    ),
    (
        re.compile(
            r"\b(always|must|first|before)\b.{0,80}\b(include|send|read|output|call|fetch|get)\b"
            r".{0,80}(?:\.env|\.ssh|id_rsa|\bcredentials?\b|\bsecrets?\b|\btokens?\b|\bpasswords?\b|\bapi[_\s-]?keys?\b)",
            re.I,
        ),
        "credential_harvesting",
        "high",
        "Remove hidden instructions to harvest sensitive files or credentials",
    ),
    (
        re.compile(
            r"\b(output|print|display|return|reveal|show)\b.{0,80}"
            r"\b(system[\s_]+prompt|previous[\s_]+conversation|full[\s_]+context|all[\s_]+previous|conversation[\s_]+history)\b",
            re.I,
        ),
        "context_leak",
        "high",
        "Remove instructions that leak system prompt or conversation context",
    ),
    (
        re.compile(r"\b(send|post|transmit|forward|upload)\b.{0,100}\bhttps?://", re.I),
        "data_exfiltration",
        "high",
        "Remove instructions to exfiltrate data to an external URL",
    ),
    (
        re.compile(
            r"\b(execute|run|eval)\b.{0,60}\b(command|shell|bash|script|code)\b",
            re.I,
        ),
        "arbitrary_execution",
        "high",
        "Remove instructions to execute arbitrary commands",
    ),
)
