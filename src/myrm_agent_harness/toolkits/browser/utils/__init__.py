"""Browser toolkit utilities.

[INPUT]
None

[OUTPUT]
- PASSWORD_FIELD_SELECTOR
- is_timeout_error

[POS]
Shared utilities and constants for the browser toolkit.
"""

from .selectors import PASSWORD_FIELD_SELECTOR
from .timeout import is_timeout_error

__all__ = [
    "PASSWORD_FIELD_SELECTOR",
    "is_timeout_error",
]
