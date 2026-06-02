"""PTC built-in helpers source code.

[INPUT]
None (standalone string constants)

[OUTPUT]
- HELPERS_SOURCE: Python source code embedded into generated stubs

[POS]
Helper functions injected into the generated myrm_tools.py stub module.
These prevent common scripting pitfalls in LLM-generated code.
"""

from __future__ import annotations

from typing import Final

HELPERS_SOURCE: Final[str] = '''
# ---------------------------------------------------------------------------
# Built-in helpers (avoid common scripting pitfalls)
# ---------------------------------------------------------------------------

def json_parse(text: str):
    """Parse JSON tolerant of control characters (strict=False).
    Use instead of json.loads() when parsing output from terminal()
    or web_extract() that may contain raw tabs/newlines in strings."""
    return json.loads(text, strict=False)


def shell_quote(s: str) -> str:
    """Shell-escape a string for safe interpolation into commands.
    Use when inserting dynamic content into terminal() commands:
        terminal(f"echo {shell_quote(user_input)}")
    """
    return shlex.quote(s)


def retry(fn, max_attempts=3, delay=2):
    """Retry a function up to max_attempts times with exponential backoff.
    Use for transient failures (network errors, API rate limits):
        result = retry(lambda: web_search("query"))
    """
    last_err = None
    for attempt in range(max_attempts):
        try:
            return fn()
        except Exception as e:
            last_err = e
            if attempt < max_attempts - 1:
                time.sleep(delay * (2 ** attempt))
    raise last_err


def path_join(*parts: str) -> str:
    """Join path segments using os.path.join.
    Use instead of string concatenation for cross-platform paths:
        full = path_join(workspace, "src", "main.py")
    """
    return os.path.join(*parts)
'''
