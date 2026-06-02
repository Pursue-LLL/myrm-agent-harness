"""Common utility functions for code executors.

Provides artifact filtering, output truncation, and error extraction.

[INPUT]
- (none)

[OUTPUT]
- should_ignore_artifact: Check if a file should be ignored during artifact collect...
- should_filter_skill_resource: Check if a file is a skill resource that should be filter...
- truncate_output: Truncate oversized output, preserving head and tail.
- extract_short_error: Extract key error information from a traceback.

[POS]
Common utility functions for code executors.
"""

from pathlib import Path

from myrm_agent_harness.utils.text_utils import smart_truncate

# File patterns to ignore during artifact collection (temp/system files)
IGNORED_ARTIFACT_PATTERNS = [
    "_metadata.json",
    ".DS_Store",
    "__pycache__",
    "*.pyc",
    ".git",
    ".gitignore",
    "run.py",
    "user_code.py",
]


def should_ignore_artifact(filename: str) -> bool:
    """Check if a file should be ignored during artifact collection.

    Args:
        filename: Filename (without path).

    Returns:
        True if the file should be ignored.
    """
    for pattern in IGNORED_ARTIFACT_PATTERNS:
        if pattern.startswith("*"):
            if filename.endswith(pattern[1:]):
                return True
        elif pattern in filename:
            return True
    return False


def should_filter_skill_resource(relative_path: str | Path) -> bool:
    """Check if a file is a skill resource that should be filtered from artifacts.

    Files under ``.claude/skills/`` are treated as system resources (like
    node_modules or .venv), not user-generated output. Skill output should
    be placed in the workspace root or an output/ directory.

    Args:
        relative_path: Path relative to workspace root.

    Returns:
        True if the file is a skill resource.

    Examples:
        >>> should_filter_skill_resource(".claude/skills/ui-ux-pro-max/data/colors.csv")
        True
        >>> should_filter_skill_resource("output.html")
        False
    """
    path_parts = Path(relative_path).parts
    return len(path_parts) >= 2 and path_parts[0] == ".claude" and path_parts[1] == "skills"


# ============================================================
# Output size limits
# ============================================================

# Max output chars (prevents OOM and oversized LLM context)
MAX_OUTPUT_CHARS = 200_000


def truncate_output(text: str, max_chars: int = MAX_OUTPUT_CHARS) -> str:
    """Truncate oversized output, preserving head and tail.

    Execution output is tail-heavy (latest output is most relevant),
    so we use 70% tail budget by default. When the tail contains
    error diagnostics, smart_truncate further increases the tail share.
    """
    return smart_truncate(text, max_chars, tail_ratio=0.7)


def extract_short_error(error: str | None) -> str | None:
    """Extract key error information from a traceback.

    Strategy:
    1. MCPError: preserve full content from MCPError onwards
    2. Find last exception line (ErrorType: message)
    3. Fallback: last non-empty line
    4. Limit to 1000 characters

    Args:
        error: Full traceback string.

    Returns:
        Short error message, or None if input is empty.
    """
    if not error:
        return None

    if "MCPError:" in error:
        start = error.find("MCPError:")
        return error[start : start + 1000]

    lines = [line.strip() for line in error.strip().split("\n") if line.strip()]
    if not lines:
        return error[:1000]

    for line in reversed(lines):
        if ": " in line and not line.startswith("File ") and not line.startswith("in "):
            return line[:1000]

    return lines[-1][:1000] if lines else error[:1000]
