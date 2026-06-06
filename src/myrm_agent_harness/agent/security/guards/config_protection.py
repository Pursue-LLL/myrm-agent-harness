"""Configuration Protection Gate.

Blocks unauthorized modifications to critical configuration files
(like .eslintrc, tsconfig.json) to steer the agent towards fixing
source code rather than weakening linters.

[INPUT]
- (none - self-contained)

[OUTPUT]
- check_config_protection: pure function to validate tool inputs for config mutations

[POS]
Pre-call guard for file mutation tools to prevent config weakening.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# List of critical configuration files to protect
_PROTECTED_FILES = frozenset(
    [
        # ESLint
        ".eslintrc",
        ".eslintrc.js",
        ".eslintrc.cjs",
        ".eslintrc.json",
        ".eslintrc.yml",
        ".eslintrc.yaml",
        "eslint.config.js",
        "eslint.config.mjs",
        "eslint.config.cjs",
        "eslint.config.ts",
        "eslint.config.mts",
        "eslint.config.cts",
        # Prettier
        ".prettierrc",
        ".prettierrc.js",
        ".prettierrc.cjs",
        ".prettierrc.json",
        ".prettierrc.yml",
        ".prettierrc.yaml",
        "prettier.config.js",
        "prettier.config.cjs",
        "prettier.config.mjs",
        # Biome
        "biome.json",
        "biome.jsonc",
        # Ruff
        ".ruff.toml",
        "ruff.toml",
        # TypeScript
        "tsconfig.json",
        "tsconfig.node.json",
        "tsconfig.app.json",
        "tsconfig.base.json",
        # Shell / Style / Markdown
        ".shellcheckrc",
        ".stylelintrc",
        ".stylelintrc.json",
        ".stylelintrc.yml",
        ".markdownlint.json",
        ".markdownlint.yaml",
        # Cursor/AI Rules
        ".cursorrules",
        ".cursor/rules/rule.mdc",
    ]
)

# Known file mutating tools in open-perplexity
_MUTATION_TOOLS = frozenset(
    [
        "edit_file",
        "write_file",
        "str_replace",
        "str_replace_multiple",
        "execute_bash",
        "run_bash",
        "run_terminal_command",
    ]
)


def check_config_protection(tool_name: str, tool_args: dict[str, Any]) -> str | None:
    """Check if the tool call attempts to mutate a protected config file.

    Args:
        tool_name: The name of the tool being called.
        tool_args: The arguments passed to the tool.

    Returns:
        str | None: The error message if blocked, None if allowed.
    """
    if tool_name not in _MUTATION_TOOLS:
        return None

    target_files: list[str] = []

    # Extract target file paths based on standard tool arguments
    if tool_name in {"edit_file", "write_file", "str_replace", "str_replace_multiple"}:
        path = tool_args.get("path")
        if isinstance(path, str):
            target_files.append(path)
        # Handle cases where multiple paths might be passed (e.g., list of edits)
        paths = tool_args.get("paths")
        if isinstance(paths, list):
            target_files.extend(str(p) for p in paths if isinstance(p, str))

    elif tool_name in {"execute_bash", "run_bash", "run_terminal_command"}:
        command = tool_args.get("command")
        if isinstance(command, str):
            # Extremely simple heuristic for bash commands mutating configs
            for protected in _PROTECTED_FILES:
                # If the protected file is mentioned and it looks like a mutation
                if protected in command and any(
                    mut_op in command
                    for mut_op in (
                        ">",
                        "sed ",
                        "awk ",
                        "rm ",
                        "touch ",
                        "mv ",
                        "cp ",
                        "nano ",
                        "vim ",
                        "vi ",
                    )
                ):
                    return (
                        f"Config Protection Gate triggered: Attempted to mutate protected config file '{protected}' "
                        f"via bash command. Please fix the source code instead of weakening configuration."
                    )

    for file_path in target_files:
        # Extract the filename from the path
        # Use simple string split to handle both / and \\ without importing os
        filename = file_path.split("/")[-1].split("\\")[-1]

        if filename in _PROTECTED_FILES:
            return (
                f"Config Protection Gate triggered: Attempted to modify protected config file '{filename}'. "
                f"Please fix the source code instead of weakening the linter/formatter configuration."
            )

    return None
