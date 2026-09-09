"""Category bucket collision and path redirection shield for skill installations.

[INPUT]
- pathlib.Path targets for installation/uninstallation

[OUTPUT]
- CategoryBucketCollisionError, PathRedirectionError, is_category_bucket, is_path_redirect, validate_safe_install_target

[POS]
myrm_agent_harness.backends.skills.scanning.category_guard
Thin compatibility facade forwarding to path_security.py (SSOT).
"""

from __future__ import annotations

from myrm_agent_harness.backends.skills.scanning.path_security import (
    CategoryBucketCollisionError,
    PathRedirectSecurityError,
    PathRedirectSecurityError as PathRedirectionError,
    assert_safe_install_target,
    assert_safe_install_target as validate_safe_install_target,
    is_category_bucket,
    is_path_redirect,
)

__all__ = [
    "CategoryBucketCollisionError",
    "PathRedirectSecurityError",
    "PathRedirectionError",
    "assert_safe_install_target",
    "is_category_bucket",
    "is_path_redirect",
    "validate_safe_install_target",
]
