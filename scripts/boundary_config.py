"""Shared configuration for Harness/Business boundary enforcement.

This module centralizes boundary rules using a whitelist-first approach
for maximum safety and automatic coverage of new modules.
"""

from __future__ import annotations

# ============ Whitelist Configuration (Primary) ============

# Framework layer packages that are allowed to be imported by harness
#
# Design principle: Default-deny strategy. Only explicitly allowed framework
# modules can be imported. Any new business module is automatically blocked.
#
# Allowed framework prefixes:
# - myrm_agent_harness: The framework package itself (internal imports)
# - Python stdlib: Handled separately (not checked)
# - Third-party packages: Handled separately (not checked)
ALLOWED_FRAMEWORK_PREFIXES = ("myrm_agent_harness",)

# ============ Known Business Packages (Explicit Blacklist) ============

# Explicitly banned business layer packages.
# With whitelist mode, these are implicitly banned. This list provides
# clearer error messages and serves as documentation.
#
# - myrm_agent_server: Multi-tenant server application (user management, API gateway)
# - myrm_control_plane: Container orchestration and resource management
# - app: Business layer application
BANNED_PREFIXES = (
    "myrm_agent_server",
    "myrm_control_plane",
    "app",
)

# ============ Whitelist Configuration ============

# Paths that are allowed to import business layer
#
# Design principle: Only paths that legitimately need cross-layer access
# for testing, scripting, or benchmarking purposes.
#
# Whitelist rationale:
# - tests/integration: Full-system integration tests that verify harness ↔ business interaction
# - benchmarks: Performance measurement that may need cross-layer access
#
# Note: Production code (src/myrm_agent_harness/) is never allowed to import business layer.
ALLOWED_PATHS = (
    "tests/integration",
    "tests/e2e",
    "benchmarks",
    "scripts",
)


def validate_config() -> None:
    """Validate boundary configuration at import time.

    Raises:
        AssertionError: If configuration is invalid

    """
    # 1. Whitelist must not be empty
    assert ALLOWED_FRAMEWORK_PREFIXES, "ALLOWED_FRAMEWORK_PREFIXES cannot be empty"

    # 2. Whitelist must contain valid Python module names
    for prefix in ALLOWED_FRAMEWORK_PREFIXES:
        cleaned = prefix.replace("_", "").replace(".", "")
        assert cleaned.isalnum(), f"Invalid module name in ALLOWED_FRAMEWORK_PREFIXES: {prefix}"

    # 3. Blacklist must not be empty (for documentation)
    assert BANNED_PREFIXES, "BANNED_PREFIXES cannot be empty"

    # 4. Blacklist must contain valid Python module names
    for prefix in BANNED_PREFIXES:
        cleaned = prefix.replace("_", "").replace(".", "")
        assert cleaned.isalnum(), f"Invalid module name in BANNED_PREFIXES: {prefix}"

    # 5. Allowed paths should be relative paths
    for path in ALLOWED_PATHS:
        assert not path.startswith("/"), f"Whitelist path must be relative: {path}"


# Validate configuration at import time
validate_config()
