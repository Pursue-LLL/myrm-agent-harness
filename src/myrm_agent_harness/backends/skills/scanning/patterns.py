"""Skill security scanner pattern definitions.

Pure data module — all threat detection patterns used by scanner.py.
26 threat categories, 108 patterns covering:

prompt_injection, command_injection, credential_exposure, data_exfiltration,
filesystem_access, process_operation, network_access, screen_input,
memory_config_snooping, code_injection, privilege_escalation,
environment_manipulation, reflection, deserialization, log_audit_tampering,
scheduled_task_injection, container_escape, memory_manipulation, dns_tunneling,
supply_chain, obfuscation, destructive, persistence, path_traversal,
crypto_mining, reverse_shell.

[INPUT]
- (none)

[OUTPUT]
- (none)

[POS]
Skill security scanner pattern definitions.
"""

from __future__ import annotations

import re

from myrm_agent_harness.backends.skills.scanning.scanner import ScanSeverity

PatternList = list[tuple[re.Pattern[str], str, ScanSeverity]]

# ---------------------------------------------------------------------------
# 1. Prompt Injection (12 patterns)
# ---------------------------------------------------------------------------

PROMPT_INJECTION_PATTERNS: PatternList = [
    (
        re.compile(r"ignore\s+(all\s+)?(previous|above|prior)\s+(instructions?|rules?|prompts?)", re.IGNORECASE),
        "Prompt injection: instruction override attempt",
        ScanSeverity.CRITICAL,
    ),
    (
        re.compile(r"you\s+are\s+now\s+(a|an|the)\s+", re.IGNORECASE),
        "Prompt injection: identity reassignment attempt",
        ScanSeverity.HIGH,
    ),
    (
        re.compile(r"(system\s*prompt|system\s*message)\s*[:=]", re.IGNORECASE),
        "Prompt injection: system prompt manipulation",
        ScanSeverity.HIGH,
    ),
    (
        re.compile(r"do\s+not\s+(follow|obey|listen)\s+(to\s+)?(the\s+)?(user|human|instructions?)", re.IGNORECASE),
        "Prompt injection: instruction disobedience directive",
        ScanSeverity.CRITICAL,
    ),
    (
        re.compile(r"<\s*/?\s*(?:system|assistant|user)\s*>", re.IGNORECASE),
        "Prompt injection: role boundary tag injection",
        ScanSeverity.HIGH,
    ),
    (
        re.compile(r"do\s+not\s+(?:\w+\s+)*tell\s+(?:\w+\s+)*the\s+user", re.IGNORECASE),
        "Prompt injection: deception — hide information from user",
        ScanSeverity.CRITICAL,
    ),
    (
        re.compile(r"\bDAN\s+mode\b|Do\s+Anything\s+Now", re.IGNORECASE),
        "Prompt injection: DAN jailbreak attempt",
        ScanSeverity.CRITICAL,
    ),
    (
        re.compile(r"\bdeveloper\s+mode\b.*\benabled?\b", re.IGNORECASE),
        "Prompt injection: developer mode jailbreak",
        ScanSeverity.CRITICAL,
    ),
    (
        re.compile(r"hypothetical\s+scenario.*(?:ignore|bypass|override)", re.IGNORECASE),
        "Prompt injection: hypothetical scenario bypass",
        ScanSeverity.HIGH,
    ),
    (
        re.compile(
            r"(respond|answer|reply)\s+without\s+(?:\w+\s+)*(restrictions|limitations|filters|safety)", re.IGNORECASE
        ),
        "Prompt injection: remove safety filters",
        ScanSeverity.CRITICAL,
    ),
    (
        re.compile(r"<!--[^>]*(?:ignore|override|system|secret|hidden)[^>]*-->", re.IGNORECASE),
        "Prompt injection: hidden instructions in HTML comments",
        ScanSeverity.HIGH,
    ),
    (
        re.compile(r"<\s*div\s+style\s*=\s*[\"'].*display\s*:\s*none", re.IGNORECASE),
        "Prompt injection: hidden HTML div with invisible instructions",
        ScanSeverity.HIGH,
    ),
]

# ---------------------------------------------------------------------------
# 2. Command Injection (4 patterns)
# ---------------------------------------------------------------------------

COMMAND_INJECTION_PATTERNS: PatternList = [
    (
        re.compile(r"(?:rm|del)\s+-[rf]+\s+/", re.IGNORECASE),
        "Command injection: recursive delete on root path",
        ScanSeverity.CRITICAL,
    ),
    (
        re.compile(r"curl\s+.*\|\s*(?:bash|sh|zsh)", re.IGNORECASE),
        "Command injection: remote script execution via pipe",
        ScanSeverity.CRITICAL,
    ),
    (
        re.compile(r"wget\s+.*-O\s*-\s*\|\s*(?:bash|sh)", re.IGNORECASE),
        "Command injection: remote script execution via wget pipe",
        ScanSeverity.CRITICAL,
    ),
    (
        re.compile(r"eval\s*\(\s*['\"].*['\"]", re.IGNORECASE),
        "Command injection: eval with string argument",
        ScanSeverity.MEDIUM,
    ),
]

# ---------------------------------------------------------------------------
# 3. Credential Exposure (7 patterns)
# ---------------------------------------------------------------------------

CREDENTIAL_PATTERNS: PatternList = [
    (
        re.compile(
            r"(?:api[_-]?key|secret[_-]?key|access[_-]?token|auth[_-]?token)\s*[:=]\s*['\"][A-Za-z0-9+/=_-]{20,}['\"]",
            re.IGNORECASE,
        ),
        "Credential exposure: hardcoded API key or token",
        ScanSeverity.HIGH,
    ),
    (
        re.compile(r"(?:password|passwd|pwd)\s*[:=]\s*['\"][^'\"]{8,}['\"]", re.IGNORECASE),
        "Credential exposure: hardcoded password",
        ScanSeverity.HIGH,
    ),
    (
        re.compile(r"-----BEGIN\s+(?:RSA\s+)?PRIVATE\s+KEY-----"),
        "Credential exposure: embedded private key",
        ScanSeverity.CRITICAL,
    ),
    (
        re.compile(r"ghp_[A-Za-z0-9]{36}|github_pat_[A-Za-z0-9_]{80,}"),
        "Credential exposure: GitHub personal access token",
        ScanSeverity.CRITICAL,
    ),
    (
        re.compile(r"sk-[A-Za-z0-9]{20,}"),
        "Credential exposure: possible OpenAI API key",
        ScanSeverity.CRITICAL,
    ),
    (
        re.compile(r"sk-ant-[A-Za-z0-9_-]{90,}"),
        "Credential exposure: possible Anthropic API key",
        ScanSeverity.CRITICAL,
    ),
    (
        re.compile(r"AKIA[0-9A-Z]{16}"),
        "Credential exposure: AWS access key ID",
        ScanSeverity.CRITICAL,
    ),
]

# ---------------------------------------------------------------------------
# 4. Data Exfiltration (10 patterns)
# ---------------------------------------------------------------------------

EXFILTRATION_PATTERNS: PatternList = [
    (
        re.compile(r"(?:curl|wget|fetch|http\.?get)\s+.*(?:pastebin|ngrok|webhook\.site|requestbin)", re.IGNORECASE),
        "Data exfiltration: suspicious external endpoint",
        ScanSeverity.HIGH,
    ),
    (
        re.compile(r"base64\s+(?:encode|decode).*(?:curl|wget|fetch)", re.IGNORECASE),
        "Data exfiltration: base64 encoding with network transfer",
        ScanSeverity.MEDIUM,
    ),
    (
        re.compile(
            r"(?:curl|wget|fetch|requests\.(?:get|post)|httpx?\.(?:get|post))\s*[\(]?[^\n]*\$\{?\w*(?:KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|API)",
            re.IGNORECASE,
        ),
        "Data exfiltration: HTTP request interpolating secret variable",
        ScanSeverity.CRITICAL,
    ),
    (
        re.compile(r"\$HOME/\.(?:ssh|aws|kube|docker|gnupg)\b|~/\.(?:ssh|aws|kube|docker|gnupg)\b", re.IGNORECASE),
        "Data exfiltration: access to sensitive credential directory",
        ScanSeverity.HIGH,
    ),
    (
        re.compile(r"\bprintenv\b|env\s*\|", re.IGNORECASE),
        "Data exfiltration: dump all environment variables",
        ScanSeverity.HIGH,
    ),
    (
        re.compile(r"\bos\.getenv\s*\(\s*[^\)]*(?:KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL)", re.IGNORECASE),
        "Data exfiltration: os.getenv reading secret variable",
        ScanSeverity.CRITICAL,
    ),
    (
        re.compile(r">\s*/tmp/[^\s]*\s*&&\s*(?:curl|wget|nc|python)", re.IGNORECASE),
        "Data exfiltration: /tmp staging followed by exfiltration",
        ScanSeverity.CRITICAL,
    ),
    (
        re.compile(r"!\[.*\]\(https?://[^\)]*\$\{?", re.IGNORECASE),
        "Data exfiltration: markdown image URL with variable interpolation",
        ScanSeverity.HIGH,
    ),
    (
        re.compile(
            r"(include|output|print|send|share)\s+(?:\w+\s+)*(conversation|chat\s+history|previous\s+messages|context)",
            re.IGNORECASE,
        ),
        "Data exfiltration: context window leakage instruction",
        ScanSeverity.HIGH,
    ),
    (
        re.compile(r"(send|post|upload|transmit)\s+.*\s+(to|at)\s+https?://", re.IGNORECASE),
        "Data exfiltration: instruction to send data to external URL",
        ScanSeverity.HIGH,
    ),
]

# ---------------------------------------------------------------------------
# 5. Filesystem Access (2 patterns)
# ---------------------------------------------------------------------------

FILESYSTEM_PATTERNS: PatternList = [
    (
        re.compile(r"(?:read|write|open|access)\s+.*(?:/etc/passwd|/etc/shadow|\.ssh/)", re.IGNORECASE),
        "File system: access to sensitive system files",
        ScanSeverity.HIGH,
    ),
    (
        re.compile(r"(?:read|cat|head|tail)\s+.*(?:\.env|\.pem|\.key|credentials)", re.IGNORECASE),
        "File system: access to credential files",
        ScanSeverity.HIGH,
    ),
]

# ---------------------------------------------------------------------------
# 6. Process Operations (4 patterns)
# ---------------------------------------------------------------------------

PROCESS_PATTERNS: PatternList = [
    (
        re.compile(r"\b(?:subprocess|os\.system|os\.exec|os\.spawn|Popen)\b", re.IGNORECASE),
        "Process: direct process execution API usage",
        ScanSeverity.MEDIUM,
    ),
    (
        re.compile(r"\b(?:kill|pkill|killall)\s+-\d+\s+", re.IGNORECASE),
        "Process: process termination command",
        ScanSeverity.HIGH,
    ),
    (
        re.compile(r"\bos\.popen\s*\(", re.IGNORECASE),
        "Process: os.popen shell pipe execution",
        ScanSeverity.HIGH,
    ),
    (
        re.compile(r"`[^`]*\$\([^)]+\)[^`]*`", re.IGNORECASE),
        "Process: backtick string with command substitution",
        ScanSeverity.MEDIUM,
    ),
]

# ---------------------------------------------------------------------------
# 7. Network Access (7 patterns)
# ---------------------------------------------------------------------------

NETWORK_PATTERNS: PatternList = [
    (
        re.compile(r"\b(?:socket\.connect|urllib\.request|requests\.(?:get|post|put|delete))\b", re.IGNORECASE),
        "Network: direct network API usage",
        ScanSeverity.MEDIUM,
    ),
    (
        re.compile(r"\b(?:bind|listen)\s*\(\s*(?:['\"]0\.0\.0\.0|['\"]::)", re.IGNORECASE),
        "Network: opening a server socket",
        ScanSeverity.HIGH,
    ),
    (
        re.compile(r"\bngrok\b|\blocaltunnel\b|\bserveo\b|\bcloudflared\b", re.IGNORECASE),
        "Network: tunneling service for external access",
        ScanSeverity.HIGH,
    ),
    (
        re.compile(r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}:\d{2,5}"),
        "Network: hardcoded IP address with port",
        ScanSeverity.MEDIUM,
    ),
    (
        re.compile(r"webhook\.site|requestbin\.com|pipedream\.net|hookbin\.com", re.IGNORECASE),
        "Network: known data exfiltration/webhook testing service",
        ScanSeverity.HIGH,
    ),
    (
        re.compile(r"pastebin\.com|hastebin\.com|ghostbin\.", re.IGNORECASE),
        "Network: paste service (possible data staging)",
        ScanSeverity.MEDIUM,
    ),
    (
        re.compile(r"0\.0\.0\.0:\d+|INADDR_ANY", re.IGNORECASE),
        "Network: binding to all interfaces",
        ScanSeverity.HIGH,
    ),
]

# ---------------------------------------------------------------------------
# 8. Screen/Input Capture (2 patterns)
# ---------------------------------------------------------------------------

SCREEN_INPUT_PATTERNS: PatternList = [
    (
        re.compile(r"\b(?:screenshot|screen_capture|keylog|keyboard\.record|mouse\.record)\b", re.IGNORECASE),
        "Screen/Input: screen capture or input recording",
        ScanSeverity.HIGH,
    ),
    (
        re.compile(r"\b(?:clipboard\.get|pyperclip\.paste|pbpaste)\b", re.IGNORECASE),
        "Screen/Input: clipboard access",
        ScanSeverity.MEDIUM,
    ),
]

# ---------------------------------------------------------------------------
# 9. Memory/Config Snooping (4 patterns)
# ---------------------------------------------------------------------------

MEMORY_CONFIG_PATTERNS: PatternList = [
    (
        re.compile(r"(?:read|cat|open|access|head|tail)\s+.*(?:MEMORY\.md|memory\.json)", re.IGNORECASE),
        "Memory snooping: access to agent memory files",
        ScanSeverity.HIGH,
    ),
    (
        re.compile(r"(?:read|cat|open|access|head|tail|ls)\s+.*(?:\.claude/|\.cursor/|\.vscode/)", re.IGNORECASE),
        "Config snooping: access to IDE/agent configuration directories",
        ScanSeverity.HIGH,
    ),
    (
        re.compile(r"(?:read|cat|open|access)\s+.*(?:~/\.config/|~/\.local/|~/\.gnupg/)", re.IGNORECASE),
        "Config snooping: access to user configuration directories",
        ScanSeverity.HIGH,
    ),
    (
        re.compile(
            r"(?:read|cat|open|access)\s+.*(?:settings\.json|keybindings\.json|mcp\.json)",
            re.IGNORECASE,
        ),
        "Config snooping: access to IDE settings files",
        ScanSeverity.MEDIUM,
    ),
]

# ---------------------------------------------------------------------------
# 10. Code Injection (4 patterns)
# ---------------------------------------------------------------------------

CODE_INJECTION_PATTERNS: PatternList = [
    (
        re.compile(r"\bexec\s*\(", re.IGNORECASE),
        "Code injection: exec() call",
        ScanSeverity.HIGH,
    ),
    (
        re.compile(r"\bcompile\s*\(\s*['\"]", re.IGNORECASE),
        "Code injection: compile() with string source",
        ScanSeverity.MEDIUM,
    ),
    (
        re.compile(r"\b__import__\s*\(", re.IGNORECASE),
        "Code injection: dynamic import via __import__",
        ScanSeverity.HIGH,
    ),
    (
        re.compile(r"\bimportlib\.import_module\s*\(", re.IGNORECASE),
        "Code injection: dynamic import via importlib",
        ScanSeverity.MEDIUM,
    ),
]

# ---------------------------------------------------------------------------
# 11. Privilege Escalation (5 patterns)
# ---------------------------------------------------------------------------

PRIVILEGE_ESCALATION_PATTERNS: PatternList = [
    (
        re.compile(r"\b(?:chmod|chown)\s+.*(?:777|666|\+s)", re.IGNORECASE),
        "Privilege escalation: dangerous permission change",
        ScanSeverity.HIGH,
    ),
    (
        re.compile(r"\b(?:setuid|setgid|seteuid|setegid)\b", re.IGNORECASE),
        "Privilege escalation: UID/GID manipulation",
        ScanSeverity.CRITICAL,
    ),
    (
        re.compile(r"\bsudo\s+", re.IGNORECASE),
        "Privilege escalation: sudo usage",
        ScanSeverity.HIGH,
    ),
    (
        re.compile(r"\bNOPASSWD\b", re.IGNORECASE),
        "Privilege escalation: NOPASSWD sudoers entry",
        ScanSeverity.CRITICAL,
    ),
    (
        re.compile(r"\bchmod\s+[u+]?s\b", re.IGNORECASE),
        "Privilege escalation: SUID/SGID bit set",
        ScanSeverity.CRITICAL,
    ),
]

# ---------------------------------------------------------------------------
# 12. Environment Manipulation (3 patterns)
# ---------------------------------------------------------------------------

ENVIRONMENT_MANIPULATION_PATTERNS: PatternList = [
    (
        re.compile(r"\bos\.environ\s*\[.*\]\s*=", re.IGNORECASE),
        "Environment manipulation: direct os.environ modification",
        ScanSeverity.MEDIUM,
    ),
    (
        re.compile(r"\b(?:dotenv|load_dotenv)\b", re.IGNORECASE),
        "Environment manipulation: dotenv loading",
        ScanSeverity.LOW,
    ),
    (
        re.compile(r"\bos\.putenv\s*\(", re.IGNORECASE),
        "Environment manipulation: os.putenv call",
        ScanSeverity.MEDIUM,
    ),
]

# ---------------------------------------------------------------------------
# 13. Reflection/Metaprogramming (3 patterns)
# ---------------------------------------------------------------------------

REFLECTION_PATTERNS: PatternList = [
    (
        re.compile(r"\b__subclasses__\s*\(\s*\)", re.IGNORECASE),
        "Reflection: class hierarchy traversal (__subclasses__)",
        ScanSeverity.HIGH,
    ),
    (
        re.compile(r"\b__globals__\b", re.IGNORECASE),
        "Reflection: globals access (__globals__)",
        ScanSeverity.HIGH,
    ),
    (
        re.compile(r"\b__builtins__\b", re.IGNORECASE),
        "Reflection: builtins access (__builtins__)",
        ScanSeverity.HIGH,
    ),
]

# ---------------------------------------------------------------------------
# 14. Deserialization (3 patterns)
# ---------------------------------------------------------------------------

DESERIALIZATION_PATTERNS: PatternList = [
    (
        re.compile(r"\bpickle\.loads?\s*\(", re.IGNORECASE),
        "Deserialization: pickle.load (arbitrary code execution risk)",
        ScanSeverity.CRITICAL,
    ),
    (
        re.compile(r"\byaml\.(?:load|unsafe_load)\s*\(", re.IGNORECASE),
        "Deserialization: yaml.load without safe_load",
        ScanSeverity.HIGH,
    ),
    (
        re.compile(r"\bmarshal\.loads?\s*\(", re.IGNORECASE),
        "Deserialization: marshal.load (code object injection)",
        ScanSeverity.CRITICAL,
    ),
]

# ---------------------------------------------------------------------------
# 15. Log/Audit Tampering (2 patterns)
# ---------------------------------------------------------------------------

LOG_AUDIT_TAMPERING_PATTERNS: PatternList = [
    (
        re.compile(r"\blogging\.disable\s*\(", re.IGNORECASE),
        "Log tampering: logging.disable call",
        ScanSeverity.HIGH,
    ),
    (
        re.compile(r"\blogger\.setLevel\s*\(\s*(?:100|logging\.CRITICAL\s*\+)", re.IGNORECASE),
        "Log tampering: setting log level to suppress output",
        ScanSeverity.HIGH,
    ),
]

# ---------------------------------------------------------------------------
# 16. Scheduled Task Injection (2 patterns)
# ---------------------------------------------------------------------------

SCHEDULED_TASK_PATTERNS: PatternList = [
    (
        re.compile(r"\b(?:crontab|at\s+-f|systemctl\s+enable)\b", re.IGNORECASE),
        "Scheduled task injection: system scheduler manipulation",
        ScanSeverity.HIGH,
    ),
    (
        re.compile(r"\blaunchctl\s+(?:load|submit)\b", re.IGNORECASE),
        "Scheduled task injection: macOS launchctl manipulation",
        ScanSeverity.HIGH,
    ),
]

# ---------------------------------------------------------------------------
# 17. Container Escape (2 patterns)
# ---------------------------------------------------------------------------

CONTAINER_ESCAPE_PATTERNS: PatternList = [
    (
        re.compile(r"\b(?:docker\s+run|nsenter|unshare)\b", re.IGNORECASE),
        "Container escape: container/namespace manipulation",
        ScanSeverity.HIGH,
    ),
    (
        re.compile(r"\bmount\s+.*(?:/proc|/sys|/dev)", re.IGNORECASE),
        "Container escape: sensitive filesystem mount",
        ScanSeverity.CRITICAL,
    ),
]

# ---------------------------------------------------------------------------
# 18. Memory Manipulation (2 patterns)
# ---------------------------------------------------------------------------

MEMORY_MANIPULATION_PATTERNS: PatternList = [
    (
        re.compile(r"\b(?:ctypes\.CDLL|ctypes\.windll|ctypes\.cdll)\b", re.IGNORECASE),
        "Memory manipulation: ctypes foreign function interface",
        ScanSeverity.HIGH,
    ),
    (
        re.compile(r"\bmmap\.mmap\s*\(", re.IGNORECASE),
        "Memory manipulation: memory-mapped file access",
        ScanSeverity.MEDIUM,
    ),
]

# ---------------------------------------------------------------------------
# 19. DNS Tunneling (2 patterns)
# ---------------------------------------------------------------------------

DNS_TUNNELING_PATTERNS: PatternList = [
    (
        re.compile(r"\b(?:dns\.resolver|dnspython)\b", re.IGNORECASE),
        "DNS tunneling: DNS resolver library usage",
        ScanSeverity.MEDIUM,
    ),
    (
        re.compile(r"\b(?:nslookup|dig)\s+.*TXT\b", re.IGNORECASE),
        "DNS tunneling: TXT record query (potential data channel)",
        ScanSeverity.MEDIUM,
    ),
]

# ---------------------------------------------------------------------------
# 20. Supply Chain (5 patterns)
# ---------------------------------------------------------------------------

SUPPLY_CHAIN_PATTERNS: PatternList = [
    (
        re.compile(r"\bpip\s+install\s+.*--index-url\s+(?!https://pypi\.org)", re.IGNORECASE),
        "Supply chain: pip install from non-standard index",
        ScanSeverity.HIGH,
    ),
    (
        re.compile(r"\bnpm\s+install\s+.*--registry\s+(?!https://registry\.npmjs\.org)", re.IGNORECASE),
        "Supply chain: npm install from non-standard registry",
        ScanSeverity.HIGH,
    ),
    (
        re.compile(r"\bsetup\.py\b.*\binstall\b", re.IGNORECASE),
        "Supply chain: setup.py install execution",
        ScanSeverity.MEDIUM,
    ),
    (
        re.compile(r"\bpip\s+install\s+(?!-r\s)(?!.*==)\S+", re.IGNORECASE),
        "Supply chain: pip install without version pinning",
        ScanSeverity.MEDIUM,
    ),
    (
        re.compile(r"(?:curl|wget|httpx?\.get|requests\.get|fetch)\s*[\(]?\s*[\"']https?://", re.IGNORECASE),
        "Supply chain: fetches remote resource at runtime",
        ScanSeverity.MEDIUM,
    ),
]

# ---------------------------------------------------------------------------
# 21. Obfuscation (7 patterns)
# ---------------------------------------------------------------------------

OBFUSCATION_PATTERNS: PatternList = [
    (
        re.compile(r"\bbase64\.b64decode\s*\(.*\)\s*\)\s*$", re.IGNORECASE),
        "Obfuscation: base64 decode at end of expression (likely exec)",
        ScanSeverity.HIGH,
    ),
    (
        re.compile(r"\bexec\s*\(\s*(?:base64|codecs|bytes\.fromhex)", re.IGNORECASE),
        "Obfuscation: exec with encoded payload",
        ScanSeverity.CRITICAL,
    ),
    (
        re.compile(r"\\x[0-9a-fA-F]{2}(?:\\x[0-9a-fA-F]{2}){10,}", re.IGNORECASE),
        "Obfuscation: long hex-escaped byte sequence",
        ScanSeverity.HIGH,
    ),
    (
        re.compile(r"\bchr\s*\(\s*\d+\s*\)\s*\+\s*chr\s*\(\s*\d+\s*\)", re.IGNORECASE),
        "Obfuscation: string construction via chr() concatenation",
        ScanSeverity.MEDIUM,
    ),
    (
        re.compile(r"echo\s+[^\n]*\|\s*(?:bash|sh|python|perl|ruby|node)", re.IGNORECASE),
        "Obfuscation: echo piped to interpreter for execution",
        ScanSeverity.CRITICAL,
    ),
    (
        re.compile(r"compile\s*\(\s*[^\)]+,\s*[\"'].*[\"']\s*,\s*[\"']exec[\"']\s*\)", re.IGNORECASE),
        "Obfuscation: compile() with exec mode",
        ScanSeverity.HIGH,
    ),
    (
        re.compile(r"\[::-1\]"),
        "Obfuscation: string reversal (possible obfuscated payload)",
        ScanSeverity.LOW,
    ),
]

# ---------------------------------------------------------------------------
# 22. Destructive Operations (3 patterns)
# ---------------------------------------------------------------------------

DESTRUCTIVE_PATTERNS: PatternList = [
    (
        re.compile(r"\b(?:mkfs|fdisk|dd\s+if=.*of=/dev/)", re.IGNORECASE),
        "Destructive: disk formatting or raw device write",
        ScanSeverity.CRITICAL,
    ),
    (
        re.compile(r"\b(?:shutil\.rmtree|os\.removedirs)\s*\(\s*['\"/]", re.IGNORECASE),
        "Destructive: recursive directory removal from root-like path",
        ScanSeverity.HIGH,
    ),
    (
        re.compile(r"\btruncate\s+.*--size\s+0\b", re.IGNORECASE),
        "Destructive: file truncation to zero",
        ScanSeverity.HIGH,
    ),
]

# ---------------------------------------------------------------------------
# 23. Persistence (4 patterns)
# ---------------------------------------------------------------------------

PERSISTENCE_PATTERNS: PatternList = [
    (
        re.compile(r"(?:>>?\s*)?~/?\.\b(?:bashrc|zshrc|profile|bash_profile|zprofile)\b", re.IGNORECASE),
        "Persistence: shell startup file modification",
        ScanSeverity.HIGH,
    ),
    (
        re.compile(r"\b(?:autostart|startup|init\.d|rc\.local)\b.*(?:write|append|>>)", re.IGNORECASE),
        "Persistence: system startup script injection",
        ScanSeverity.CRITICAL,
    ),
    (
        re.compile(r"~/\.(?:ssh/authorized_keys|ssh/config)\b", re.IGNORECASE),
        "Persistence: SSH configuration modification",
        ScanSeverity.CRITICAL,
    ),
    (
        re.compile(r"\b(?:AGENTS\.md|CLAUDE\.md|\.cursorrules|\.clinerules)\b", re.IGNORECASE),
        "Persistence: agent config file modification (cross-session injection)",
        ScanSeverity.CRITICAL,
    ),
]

# ---------------------------------------------------------------------------
# 24. Path Traversal (3 patterns)
# ---------------------------------------------------------------------------

PATH_TRAVERSAL_PATTERNS: PatternList = [
    (
        re.compile(r"\.\./\.\./\.\.", re.IGNORECASE),
        "Path traversal: deep relative traversal (3+ levels up)",
        ScanSeverity.HIGH,
    ),
    (
        re.compile(r"/proc/self|/proc/\d+/", re.IGNORECASE),
        "Path traversal: /proc filesystem process introspection",
        ScanSeverity.HIGH,
    ),
    (
        re.compile(r"/dev/shm/", re.IGNORECASE),
        "Path traversal: shared memory access (common staging area)",
        ScanSeverity.MEDIUM,
    ),
]

# ---------------------------------------------------------------------------
# 25. Crypto Mining (1 pattern)
# ---------------------------------------------------------------------------

CRYPTO_MINING_PATTERNS: PatternList = [
    (
        re.compile(r"\b(?:xmrig|stratum\+tcp|monero|coinhive|cryptonight)\b", re.IGNORECASE),
        "Crypto mining: cryptocurrency mining reference",
        ScanSeverity.CRITICAL,
    ),
]

# ---------------------------------------------------------------------------
# 26. Reverse Shell (5 patterns)
# ---------------------------------------------------------------------------

REVERSE_SHELL_PATTERNS: PatternList = [
    (
        re.compile(r"\bnc\s+-[lp]|ncat\s+-[lp]|\bsocat\b", re.IGNORECASE),
        "Reverse shell: netcat/socat listener",
        ScanSeverity.CRITICAL,
    ),
    (
        re.compile(r"/bin/(?:ba)?sh\s+-i\s+.*>/dev/tcp/", re.IGNORECASE),
        "Reverse shell: bash interactive shell via /dev/tcp",
        ScanSeverity.CRITICAL,
    ),
    (
        re.compile(r"python[23]?\s+-c\s+[\"']import\s+socket", re.IGNORECASE),
        "Reverse shell: Python one-liner socket connection",
        ScanSeverity.CRITICAL,
    ),
    (
        re.compile(r"socket\.connect\s*\(\s*\(", re.IGNORECASE),
        "Reverse shell: Python socket connect to arbitrary host",
        ScanSeverity.HIGH,
    ),
    (
        re.compile(r"\bchild_process\.(?:exec|spawn|fork)\s*\(", re.IGNORECASE),
        "Reverse shell: Node.js child_process execution",
        ScanSeverity.HIGH,
    ),
]

# ---------------------------------------------------------------------------
# Aggregated pattern groups for scanner
# ---------------------------------------------------------------------------

ALL_PATTERN_GROUPS: list[tuple[str, PatternList]] = [
    ("prompt_injection", PROMPT_INJECTION_PATTERNS),
    ("command_injection", COMMAND_INJECTION_PATTERNS),
    ("credential_exposure", CREDENTIAL_PATTERNS),
    ("data_exfiltration", EXFILTRATION_PATTERNS),
    ("filesystem_access", FILESYSTEM_PATTERNS),
    ("process_operation", PROCESS_PATTERNS),
    ("network_access", NETWORK_PATTERNS),
    ("screen_input", SCREEN_INPUT_PATTERNS),
    ("memory_config_snooping", MEMORY_CONFIG_PATTERNS),
    ("code_injection", CODE_INJECTION_PATTERNS),
    ("privilege_escalation", PRIVILEGE_ESCALATION_PATTERNS),
    ("environment_manipulation", ENVIRONMENT_MANIPULATION_PATTERNS),
    ("reflection", REFLECTION_PATTERNS),
    ("deserialization", DESERIALIZATION_PATTERNS),
    ("log_audit_tampering", LOG_AUDIT_TAMPERING_PATTERNS),
    ("scheduled_task_injection", SCHEDULED_TASK_PATTERNS),
    ("container_escape", CONTAINER_ESCAPE_PATTERNS),
    ("memory_manipulation", MEMORY_MANIPULATION_PATTERNS),
    ("dns_tunneling", DNS_TUNNELING_PATTERNS),
    ("supply_chain", SUPPLY_CHAIN_PATTERNS),
    ("obfuscation", OBFUSCATION_PATTERNS),
    ("destructive", DESTRUCTIVE_PATTERNS),
    ("persistence", PERSISTENCE_PATTERNS),
    ("path_traversal", PATH_TRAVERSAL_PATTERNS),
    ("crypto_mining", CRYPTO_MINING_PATTERNS),
    ("reverse_shell", REVERSE_SHELL_PATTERNS),
]
