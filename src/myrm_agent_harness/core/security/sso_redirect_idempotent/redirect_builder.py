"""Idempotent SSO Redirect URL builder and safe navigation target validator.

Prevents open redirect vulnerabilities (e.g. WHATWG backslash bypasses) and
eliminates recursive query parameter ballooning across auth guard redirects.
"""

from urllib.parse import parse_qsl, quote_plus, urlencode, urlsplit, urlunsplit

from myrm_agent_harness.core.security.sso_redirect_idempotent.types import (
    SafeNavigationOptions,
    SsoRedirectResult,
)

SELF_EXECUTING_PROTOCOLS: frozenset[str] = frozenset(
    {
        "javascript:",
        "data:",
        "blob:",
        "file:",
        "vbscript:",
        "about:",
    }
)

SAFE_HTTP_PROTOCOLS: frozenset[str] = frozenset({"http:", "https:"})


def is_same_origin_relative_path(target: str) -> bool:
    """Validate whether target is a strictly same-origin relative path.

    The second character must not be '/' or '\\' because WHATWG URL parsing
    normalizes '\\' to '/' for special schemes, allowing '/\\\\evil.com' to
    resolve to an external host and leak authentication tokens.
    """
    if not target or not target.startswith("/"):
        return False
    return not (len(target) > 1 and target[1] in ("/", "\\"))


def is_safe_navigation_target(
    target: str,
    options: SafeNavigationOptions | None = None,
) -> bool:
    """Verify whether a navigation target is safe and does not trigger open redirect.

    Same-origin relative paths are always safe. Absolute URLs must use safe HTTP
    protocols and optionally match allowed origins. Deep links are permitted only
    when explicitly enabled and matching registered schemes.
    """
    if not target or not target.strip():
        return False

    trimmed: str = target.strip()
    if is_same_origin_relative_path(trimmed):
        return True

    try:
        split_result = urlsplit(trimmed)
    except Exception:
        return False

    scheme: str = split_result.scheme.lower()
    if not scheme:
        return False

    scheme_with_colon: str = f"{scheme}:"
    if scheme_with_colon in SELF_EXECUTING_PROTOCOLS:
        return False

    if scheme_with_colon in SAFE_HTTP_PROTOCOLS:
        if options is not None and options.allowed_origins is not None:
            netloc: str = split_result.netloc
            origin: str = f"{scheme}://{netloc}"
            return origin in options.allowed_origins
        return True

    # Custom protocol deep links
    if (
        options is not None
        and options.allow_deep_link
        and scheme in options.allowed_deep_link_schemes
    ):
        # Deep link must have a target host/action
        return bool(split_result.netloc or split_result.path)

    return False


def build_sso_redirect_url(
    redirect_uri: str,
    sso_code: str,
    param_name: str = "sso_code",
    options: SafeNavigationOptions | None = None,
) -> SsoRedirectResult:
    """Construct an idempotent redirect URL with fresh sso_code attached.

    Strips any existing occurrences of param_name to prevent recursion and
    parameter inflation across 307 auth guard round trips.
    """
    opts: SafeNavigationOptions = (
        options if options is not None else SafeNavigationOptions()
    )
    if not redirect_uri or not redirect_uri.strip():
        fallback: str = opts.fallback_url
        sep: str = "&" if "?" in fallback else "?"
        url_with_code: str = f"{fallback}{sep}{param_name}={quote_plus(sso_code)}"
        return SsoRedirectResult(
            original_uri=redirect_uri,
            redirect_url=url_with_code,
            stripped_existing_code=False,
            is_relative=True,
            is_safe_target=True,
        )

    trimmed: str = redirect_uri.strip()
    is_rel: bool = is_same_origin_relative_path(trimmed)
    is_safe: bool = is_safe_navigation_target(trimmed, opts)

    try:
        # For relative paths, borrow placeholder origin for parsing
        parse_target: str = (
            f"https://sso.invalid{trimmed}" if is_rel else trimmed
        )
        split = urlsplit(parse_target)

        existing_pairs = parse_qsl(split.query, keep_blank_values=True)
        filtered_pairs: list[tuple[str, str]] = []
        stripped: bool = False

        for k, v in existing_pairs:
            if k.lower() == param_name.lower():
                stripped = True
            else:
                filtered_pairs.append((k, v))

        filtered_pairs.append((param_name, sso_code))
        new_query: str = urlencode(filtered_pairs)

        if is_rel:
            query_part: str = f"?{new_query}" if new_query else ""
            frag_part: str = f"#{split.fragment}" if split.fragment else ""
            final_url: str = f"{split.path}{query_part}{frag_part}"
        else:
            final_url = urlunsplit(
                (split.scheme, split.netloc, split.path, new_query, split.fragment)
            )

        return SsoRedirectResult(
            original_uri=redirect_uri,
            redirect_url=final_url,
            stripped_existing_code=stripped,
            is_relative=is_rel,
            is_safe_target=is_safe,
        )

    except Exception:
        # Fallback minimal concatenation
        separator: str = "&" if "?" in trimmed else "?"
        encoded_code: str = quote_plus(sso_code)
        fallback_url: str = f"{trimmed}{separator}{param_name}={encoded_code}"
        return SsoRedirectResult(
            original_uri=redirect_uri,
            redirect_url=fallback_url,
            stripped_existing_code=False,
            is_relative=is_rel,
            is_safe_target=is_safe,
        )


def resolve_safe_redirect_target(
    target: str,
    options: SafeNavigationOptions | None = None,
) -> str:
    """Resolve redirect target, falling back to safe URL if target is unsafe."""
    opts: SafeNavigationOptions = (
        options if options is not None else SafeNavigationOptions()
    )
    if is_safe_navigation_target(target, opts):
        return target
    return opts.fallback_url
