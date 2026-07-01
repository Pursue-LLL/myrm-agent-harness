"""Activation criteria limits for skill frontmatter validation.

[INPUT]
- (none)

[OUTPUT]
- _MAX_KEYWORDS_PER_SKILL, _MAX_PATTERNS_PER_SKILL, _MAX_TAGS_PER_SKILL
- _MIN_KEYWORD_TAG_LENGTH, _MAX_PATTERN_LENGTH, _DEFAULT_MAX_CONTEXT_TOKENS

[POS]
Shared limits aligned with the ironclaw security model for skill activation fields.
"""

# Activation criteria limits (aligned with ironclaw security model)
_MAX_KEYWORDS_PER_SKILL = 20
_MAX_PATTERNS_PER_SKILL = 5
_MAX_TAGS_PER_SKILL = 10
_MIN_KEYWORD_TAG_LENGTH = 3
_MAX_PATTERN_LENGTH = 256
_DEFAULT_MAX_CONTEXT_TOKENS = 2000
