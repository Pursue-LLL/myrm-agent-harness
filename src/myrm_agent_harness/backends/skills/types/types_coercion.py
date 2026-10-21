"""Coercion helpers for skill type deserialization.

[INPUT]
- (none)

[OUTPUT]
- _coerce_str_list(): safe list-of-strings coercion for untrusted input

[POS]
Shared parsing helper for SkillRequires.from_dict and similar deserializers.
"""


def _coerce_str_list(val: object) -> list[str]:
    """Coerce a value to a list of strings (safe for untrusted input)."""
    return [str(v) for v in val] if isinstance(val, list) else []
