"""Shell command quote-stripping helpers.

[POS]
_strip_quoted_content helper for shell_command_analyzer threat detection.
"""

from __future__ import annotations

_PLACEHOLDER = "\x01"

def _strip_quoted_content(command: str) -> str:
    """Replace single-quoted string content with placeholders using a state machine.

    Character-level parsing correctly distinguishes:
    - Regular single quotes ('...'): content replaced with placeholders
    - ANSI-C quoting ($'...'): treated as opaque (already BLOCKED by Layer 1.5),
      entire span replaced with placeholders to prevent false positives in Layer 2/3
    - Double quotes ("..."): NOT stripped (allow command substitution detection)

    CRITICAL SECURITY DESIGN:
    We ONLY strip single quotes and ANSI-C quote content. Double quotes allow
    command substitution (e.g., `echo "$(rm -rf /)"`) so their content MUST remain
    visible to downstream pattern matching.

    The state machine approach (consistent with risk_classifier._split_shell_operators)
    correctly handles edge cases like `'it'\\''s'` nested quoting that regex cannot.
    """
    result: list[str] = []
    i = 0
    n = len(command)

    while i < n:
        ch = command[i]

        # Detect ANSI-C quoting: $'...'
        if ch == "$" and i + 1 < n and command[i + 1] == "'":
            result.append(_PLACEHOLDER)  # replace $
            result.append(_PLACEHOLDER)  # replace '
            i += 2
            # Consume until closing unescaped single quote
            while i < n:
                if command[i] == "\\" and i + 1 < n:
                    result.append(_PLACEHOLDER)
                    result.append(_PLACEHOLDER)
                    i += 2
                elif command[i] == "'":
                    result.append(_PLACEHOLDER)
                    i += 1
                    break
                else:
                    result.append(_PLACEHOLDER)
                    i += 1

        # Detect locale quoting: $"..."
        elif ch == "$" and i + 1 < n and command[i + 1] == '"':
            result.append(_PLACEHOLDER)  # replace $
            result.append(_PLACEHOLDER)  # replace "
            i += 2
            while i < n:
                if command[i] == "\\" and i + 1 < n:
                    result.append(_PLACEHOLDER)
                    result.append(_PLACEHOLDER)
                    i += 2
                elif command[i] == '"':
                    result.append(_PLACEHOLDER)
                    i += 1
                    break
                else:
                    result.append(_PLACEHOLDER)
                    i += 1

        # Regular single quote
        elif ch == "'":
            result.append(ch)  # preserve opening quote
            i += 1
            while i < n and command[i] != "'":
                result.append(_PLACEHOLDER)
                i += 1
            if i < n:
                result.append(ch)  # preserve closing quote
                i += 1

        else:
            result.append(ch)
            i += 1

    return "".join(result)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


