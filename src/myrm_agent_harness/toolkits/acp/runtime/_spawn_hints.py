"""Human-readable hints when external CLI/ACP spawn fails."""

from __future__ import annotations

import os

_BARE_CLI_HINTS: dict[str, str] = {
    "claude": (
        "Use Settings → Developer → External Agents with type 'cli' and Claude stream-json args, "
        "or install the Claude Code ACP adapter if you intended type 'acp'."
    ),
    "codex": (
        "Bare 'codex' is not an ACP adapter. Install @zed-industries/codex-acp or configure "
        "type 'cli' with Codex exec --json args in Settings → Developer → External Agents."
    ),
    "gemini": (
        "Configure Gemini as type 'cli' with --output-format stream-json in "
        "Settings → Developer → External Agents, or use a Gemini ACP adapter when available."
    ),
}


def format_cli_spawn_failure_message(
    command: str,
    *,
    return_code: int,
    stderr: str,
) -> str:
    """Append adapter hints when a bare CLI binary likely caused spawn failure."""
    base = f"CLI process exited with code {return_code}: {stderr[:500]}"
    binary = os.path.basename(command.split()[0] if command else "")
    hint = _BARE_CLI_HINTS.get(binary)
    if hint is None:
        return base
    return f"{base}\n\nHint: {hint}"
