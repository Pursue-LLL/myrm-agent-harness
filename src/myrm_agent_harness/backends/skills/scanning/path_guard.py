"""Filesystem path redirection and category bucket collision guard for skill installations.

[POS]
myrm_agent_harness.backends.skills.scanning.path_guard
Thin compatibility facade forwarding to path_security.py (SSOT).
"""

from __future__ import annotations

from myrm_agent_harness.backends.skills.scanning.path_security import (
    CategoryBucketCollisionError,
    CategoryBucketResult,
    PathRedirectSecurityError,
    PathRedirectionError,
    assert_safe_install_target,
    check_install_target_safety,
    is_category_bucket,
    is_path_redirect,
    validate_safe_install_target,
)

__all__ = [
    "CategoryBucketCollisionError",
    "CategoryBucketResult",
    "PathRedirectSecurityError",
    "PathRedirectionError",
    "assert_safe_install_target",
    "check_install_target_safety",
    "is_category_bucket",
    "is_path_redirect",
    "validate_safe_install_target",
]
