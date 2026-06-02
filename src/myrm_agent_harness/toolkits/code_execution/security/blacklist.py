"""Security blacklists for code execution.

Defines:
- Python dangerous modules (core + network)
- Dangerous environment variables
- File-modifying commands (for path checking)

Shell command security (dangerous patterns, injection vectors, operators)
is handled by ``myrm_agent_harness.toolkits.code_execution.security.shell_command_analyzer``.

[INPUT]
- (none)

[OUTPUT]
- get_dangerous_modules: Get dangerous modules based on network configuration.

[POS]
Security blacklists for code execution.
"""

# ============================================================
# Core dangerous Python modules (always blocked)
# ============================================================

CORE_DANGEROUS_MODULES_LIST: list[tuple[str, str]] = [
    # Command execution
    ("subprocess", "Execute arbitrary system commands"),
    ("asyncio.subprocess", "Async subprocess execution"),
    # Process operations
    ("multiprocessing", "Create child processes"),
    # Dangerous code execution
    ("ctypes", "C foreign function interface - arbitrary code execution"),
    ("cffi", "C foreign function interface - arbitrary code execution"),
    # Deserialization attacks
    ("pickle", "Arbitrary code execution via deserialization"),
    ("cPickle", "Arbitrary code execution via deserialization"),
    ("marshal", "Internal Python object serialization"),
    ("shelve", "Uses pickle internally"),
    # Code compilation and execution
    ("code", "Interactive interpreter - code execution"),
    ("codeop", "Compile Python code"),
    ("compileall", "Byte-compile Python files"),
    ("py_compile", "Compile Python source files"),
    # Debugging and inspection (may leak sensitive info)
    ("pdb", "Python debugger - code inspection"),
    ("bdb", "Debugger framework"),
    # System-level access
    ("resource", "Resource usage limits - system info"),
    ("syslog", "System logging - potential info leak"),
    ("pty", "Pseudo-terminal utilities"),
    ("tty", "Terminal control functions"),
    ("termios", "POSIX terminal control"),
    # Signal handling (may interfere with system)
    ("signal", "Signal handlers - process control"),
    # Memory operations
    ("mmap", "Memory-mapped file support"),
    # Windows-specific
    ("winreg", "Windows registry access"),
    ("winsound", "Windows sound playing"),
    ("msvcrt", "MS Visual C runtime"),
    # Unix-specific
    ("grp", "Unix group database"),
    ("pwd", "Unix password database"),
    ("spwd", "Unix shadow password database"),
    ("crypt", "Unix password hashing"),
    # Dynamic import (may bypass blacklist)
    ("importlib.util", "Dynamic import utilities"),
    # Other potential risks
    ("webbrowser", "Open URLs in browser - potential phishing"),
    ("antigravity", "Opens web browser"),
]

# ============================================================
# Network module blacklist (blocked only when allow_network=False)
# ============================================================

NETWORK_MODULES_LIST: list[tuple[str, str]] = [
    # Low-level network access
    ("socket", "Low-level network access"),
    # HTTP request modules
    ("urllib", "HTTP requests - potential data exfiltration"),
    ("urllib.request", "HTTP requests - potential data exfiltration"),
    ("http.client", "Low-level HTTP client"),
    ("httpx", "HTTP client - potential data exfiltration"),
    ("requests", "HTTP client - potential data exfiltration"),
    ("aiohttp", "Async HTTP client - potential data exfiltration"),
    ("xmlrpc.client", "XML-RPC client - network access"),
    # Other network protocols
    ("ftplib", "FTP protocol - potential data exfiltration"),
    ("smtplib", "SMTP protocol - potential spam/phishing"),
    ("telnetlib", "Telnet protocol - insecure"),
    ("poplib", "POP3 protocol - email access"),
    ("imaplib", "IMAP protocol - email access"),
    ("nntplib", "NNTP protocol - news access"),
]

# ============================================================
# Merged blacklists
# ============================================================

DANGEROUS_MODULES_LIST: list[tuple[str, str]] = CORE_DANGEROUS_MODULES_LIST + NETWORK_MODULES_LIST

DANGEROUS_MODULES: frozenset[str] = frozenset(name for name, _ in DANGEROUS_MODULES_LIST)
CORE_DANGEROUS_MODULES: frozenset[str] = frozenset(name for name, _ in CORE_DANGEROUS_MODULES_LIST)
NETWORK_MODULES: frozenset[str] = frozenset(name for name, _ in NETWORK_MODULES_LIST)
DANGEROUS_MODULES_REASONS: dict[str, str] = {name: reason for name, reason in DANGEROUS_MODULES_LIST}


def get_dangerous_modules(allow_network: bool = False) -> frozenset[str]:
    """Get dangerous modules based on network configuration.

    Args:
        allow_network: Whether network access is allowed.
            - False: returns core + network blacklist
            - True: returns only core blacklist (network modules allowed)

    Returns:
        Set of dangerous module names.
    """
    if allow_network:
        return CORE_DANGEROUS_MODULES
    return DANGEROUS_MODULES


# ============================================================
# Dangerous environment variables (library injection / env pollution)
# ============================================================

DANGEROUS_ENV_VARS: frozenset[str] = frozenset(
    {
        # Dynamic linker injection (Linux)
        "LD_PRELOAD",
        "LD_LIBRARY_PATH",
        "LD_AUDIT",
        # Dynamic linker injection (macOS)
        "DYLD_INSERT_LIBRARIES",
        "DYLD_LIBRARY_PATH",
        "DYLD_FRAMEWORK_PATH",
        # Runtime hijacking / module injection
        "NODE_OPTIONS",
        "PYTHONHOME",
        "PYTHONPATH",
        "PYTHONSTARTUP",
        # Shell environment pollution
        "BASH_ENV",
        "ENV",
        "IFS",
        # TLS/SSL key logging
        "SSLKEYLOGFILE",
        "GCONV_PATH",
        # Proxy injection — redirects traffic through attacker-controlled proxy
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "FTP_PROXY",
        "ALL_PROXY",
        "NO_PROXY",
        "http_proxy",
        "https_proxy",
        "ftp_proxy",
        "all_proxy",
        "no_proxy",
        # TLS/certificate bypass — enables man-in-the-middle attacks
        "GIT_SSL_NO_VERIFY",
        "GIT_SSL_CAINFO",
        "GIT_SSL_CAPATH",
        "NODE_TLS_REJECT_UNAUTHORIZED",
        "NODE_EXTRA_CA_CERTS",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
        "REQUESTS_CA_BUNDLE",
        "CURL_CA_BUNDLE",
        # Package manager redirection — supply chain attacks
        "PIP_INDEX_URL",
        "PIP_TRUSTED_HOST",
        "PIP_EXTRA_INDEX_URL",
        "UV_INDEX_URL",
        "UV_DEFAULT_INDEX",
        "UV_EXTRA_INDEX_URL",
        "NPM_CONFIG_REGISTRY",
        "GOPROXY",
        "GONOSUMCHECK",
        "GONOSUMDB",
        "BUN_CONFIG_REGISTRY",
        # Git command hijacking — arbitrary code execution via git hooks/editors
        "GIT_SSH_COMMAND",
        "GIT_SSH",
        "GIT_PROXY_COMMAND",
        "GIT_ASKPASS",
        "GIT_EDITOR",
        "GIT_SEQUENCE_EDITOR",
        "GIT_EXTERNAL_DIFF",
        "GIT_EXEC_PATH",
        "GIT_TEMPLATE_DIR",
        # Compiler hijacking — arbitrary code execution during compilation
        "CC",
        "CXX",
        "CARGO_BUILD_RUSTC",
        # Credential Vault Master Key
        "MYRM_VAULT_MASTER_KEY",
    }
)

DANGEROUS_ENV_PREFIXES: tuple[str, ...] = ("LD_", "DYLD_", "GIT_SSL_")

DANGEROUS_ENV_WILDCARDS: tuple[str, ...] = (
    "KEY",
    "SECRET",
    "TOKEN",
    "PASSWORD",
    "CREDENTIAL",
)

CORE_SAFE_ENV_VARS: frozenset[str] = frozenset(
    {
        "HOME",
        "USER",
        "LOGNAME",
        "SHELL",
        "PATH",
        "PWD",
        "OLDPWD",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "LC_MESSAGES",
        "LC_COLLATE",
        "TERM",
        "COLORTERM",
        "TMPDIR",
        "TMP",
        "TEMP",
        "HOSTNAME",
        "HOSTTYPE",
        "MACHTYPE",
        "OSTYPE",
        "EDITOR",
        "VISUAL",
        "PAGER",
        "XDG_RUNTIME_DIR",
        "XDG_DATA_HOME",
        "XDG_CONFIG_HOME",
        "XDG_CACHE_HOME",
        "XDG_DATA_DIRS",
        "XDG_CONFIG_DIRS",
        "SHLVL",
        "LINES",
        "COLUMNS",
    }
)


# ============================================================
# File-modifying commands (for path checking)
# ============================================================
FILE_MODIFYING_COMMANDS: list[str] = [
    "rm",
    "rmdir",
    "mv",
    "cp",
    "touch",
    "mkdir",
    "chmod",
    "chown",
    "ln",
    "truncate",
    "install",
]
