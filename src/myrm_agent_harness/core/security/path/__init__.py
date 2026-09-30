"""Path security domain — the single import surface for every path protection rule.

Three modules, one responsibility each:

- ``pattern``    — glob matcher engine (`*`/`?`/`**`/character classes, case-insensitive by default)
- ``filesystem`` — generic path safety: dangerous roots, device names, boundary, safe join, coercion
- ``rules``      — protected-path policy: which files must not be touched, and the predicates that read the rules

Consumers import predicates from this package (``core.security.path``) and reach for
``core.security.path.pattern`` only when they need the raw matcher. ``__all__`` is
declared so the ``agent.security.path_security`` shim forwards exactly this API — without
it, a wildcard re-export would also republish ``os``/``Path`` and invite callers to
bypass the predicates that carry the security policy.

[INPUT]
- (none — pure data + logic package)

[OUTPUT]
- is_dangerous_path, is_blocked_device_path, is_within_boundary, safe_join_path, coerce_filesystem_path, is_content_not_path
- is_sensitive_file, is_protected_instruction_file, is_evidence_readonly_file
- DANGEROUS_PATHS, BLOCKED_DEVICE_NAMES, MAX_PATH_LENGTH
- SENSITIVE_FILE_PATTERNS, PROTECTED_INSTRUCTION_PATTERNS, EVIDENCE_READONLY_PATTERNS

[POS]
Aggregation facade for the path security domain.
"""

from myrm_agent_harness.core.security.path.filesystem import (
    BLOCKED_DEVICE_NAMES as BLOCKED_DEVICE_NAMES,
)
from myrm_agent_harness.core.security.path.filesystem import (
    DANGEROUS_PATHS as DANGEROUS_PATHS,
)
from myrm_agent_harness.core.security.path.filesystem import (
    MAX_PATH_LENGTH as MAX_PATH_LENGTH,
)
from myrm_agent_harness.core.security.path.filesystem import (
    coerce_filesystem_path as coerce_filesystem_path,
)
from myrm_agent_harness.core.security.path.filesystem import (
    is_blocked_device_path as is_blocked_device_path,
)
from myrm_agent_harness.core.security.path.filesystem import (
    is_content_not_path as is_content_not_path,
)
from myrm_agent_harness.core.security.path.filesystem import (
    is_dangerous_path as is_dangerous_path,
)
from myrm_agent_harness.core.security.path.filesystem import (
    is_within_boundary as is_within_boundary,
)
from myrm_agent_harness.core.security.path.filesystem import (
    safe_join_path as safe_join_path,
)
from myrm_agent_harness.core.security.path.rules import (
    EVIDENCE_READONLY_PATTERNS as EVIDENCE_READONLY_PATTERNS,
)
from myrm_agent_harness.core.security.path.rules import (
    PROTECTED_INSTRUCTION_PATTERNS as PROTECTED_INSTRUCTION_PATTERNS,
)
from myrm_agent_harness.core.security.path.rules import (
    SENSITIVE_FILE_PATTERNS as SENSITIVE_FILE_PATTERNS,
)
from myrm_agent_harness.core.security.path.rules import (
    is_evidence_readonly_file as is_evidence_readonly_file,
)
from myrm_agent_harness.core.security.path.rules import (
    is_protected_instruction_file as is_protected_instruction_file,
)
from myrm_agent_harness.core.security.path.rules import (
    is_sensitive_file as is_sensitive_file,
)

__all__ = (
    "BLOCKED_DEVICE_NAMES",
    "DANGEROUS_PATHS",
    "EVIDENCE_READONLY_PATTERNS",
    "MAX_PATH_LENGTH",
    "PROTECTED_INSTRUCTION_PATTERNS",
    "SENSITIVE_FILE_PATTERNS",
    "coerce_filesystem_path",
    "is_blocked_device_path",
    "is_content_not_path",
    "is_dangerous_path",
    "is_evidence_readonly_file",
    "is_protected_instruction_file",
    "is_sensitive_file",
    "is_within_boundary",
    "safe_join_path",
)
