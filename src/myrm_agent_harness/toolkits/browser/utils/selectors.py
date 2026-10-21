"""Browser toolkit shared selectors.

[INPUT]
None

[OUTPUT]
- PASSWORD_FIELD_SELECTOR: A robust CSS selector for identifying password fields.

[POS]
Shared constants and selectors for the browser toolkit.
"""

# A highly robust CSS selector for identifying password fields across various frontend implementations.
# Covers native type="password", as well as common name/id/placeholder/aria-label patterns
# used in "show password" toggles or custom components.
PASSWORD_FIELD_SELECTOR = (
    'input[type="password"], '
    'input[autocomplete*="password" i], '
    'input[name*="password" i], input[name*="passwd" i], input[name*="pwd" i], input[name*="passcode" i], '
    'input[id*="password" i], input[id*="passwd" i], input[id*="pwd" i], input[id*="passcode" i], '
    'input[placeholder*="password" i], input[placeholder*="passwd" i], input[placeholder*="pwd" i], input[placeholder*="passcode" i], '
    'input[aria-label*="password" i], input[aria-label*="passwd" i], input[aria-label*="pwd" i], input[aria-label*="passcode" i], '
    'textarea[name*="password" i], textarea[name*="passwd" i], textarea[name*="pwd" i], textarea[name*="passcode" i], '
    'textarea[id*="password" i], textarea[id*="passwd" i], textarea[id*="pwd" i], textarea[id*="passcode" i]'
)
