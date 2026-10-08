"""URL Sanitizer and Idempotent SSO Redirect URL Builder.

[INPUT]
- Target redirect URLs, authorization codes, param names.

[OUTPUT]
- Sanitized, idempotent redirect URLs free from redundant query params.

[POS]
- Harness core security engine for IHUI-AI #2728e745 idempotent redirect and open-redirect defenses.
"""

from __future__ import annotations

from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

from .types import (
    SsoRedirectBuildResult,
    SsoRedirectValidation,
    UrlPathCategory,
)


class SsoUrlSanitizer:
    """Sanitizes redirect URLs and builds idempotent SSO redirect URLs."""

    @staticmethod
    def is_same_origin_relative_path(target: str) -> bool:
        """Verify whether a target is a safe same-origin relative path.

        Security boundary against WHATWG special authority slashes:
        - Must start with '/'
        - Second character must NOT be '/' or '\\'
        """
        if not target.startswith("/"):
            return False
        if len(target) > 1:
            second = target[1]
            if second in ("/", "\\"):
                return False
        return True

    def validate_redirect_target(
        self,
        target_url: str,
        allowed_absolute_hosts: frozenset[str] | None = None,
    ) -> SsoRedirectValidation:
        """Validate whether a target redirect URL is permissible without open redirect risks."""
        if not target_url or not target_url.strip():
            return SsoRedirectValidation(
                target_url=target_url,
                is_safe=False,
                category=UrlPathCategory.INVALID,
                reason="Target URL is empty",
            )

        trimmed = target_url.strip()

        # 1. Safe relative path
        if self.is_same_origin_relative_path(trimmed):
            return SsoRedirectValidation(
                target_url=trimmed,
                is_safe=True,
                category=UrlPathCategory.SAFE_RELATIVE,
            )

        # 2. Unsafe relative path (e.g. //evil.com or /\evil.com)
        if trimmed.startswith(("/", "\\")):
            return SsoRedirectValidation(
                target_url=trimmed,
                is_safe=False,
                category=UrlPathCategory.UNSAFE_RELATIVE,
                reason="Target URL starts with scheme-relative or backslash prefix",
            )

        # 3. Check parsed scheme
        try:
            parts = urlsplit(trimmed)
            if parts.scheme in ("http", "https"):
                if (
                    allowed_absolute_hosts
                    and parts.netloc.lower() in allowed_absolute_hosts
                ):
                    return SsoRedirectValidation(
                        target_url=trimmed,
                        is_safe=True,
                        category=UrlPathCategory.ABSOLUTE,
                    )
                if not allowed_absolute_hosts:
                    return SsoRedirectValidation(
                        target_url=trimmed,
                        is_safe=True,
                        category=UrlPathCategory.ABSOLUTE,
                    )
                return SsoRedirectValidation(
                    target_url=trimmed,
                    is_safe=False,
                    category=UrlPathCategory.ABSOLUTE,
                    reason=f"Host '{parts.netloc}' not in allowed absolute hosts",
                )
            if parts.scheme and parts.scheme not in (
                "http",
                "https",
                "javascript",
                "data",
                "vbscript",
            ):
                # Custom deep link scheme (e.g. myrm://, ihui://)
                return SsoRedirectValidation(
                    target_url=trimmed,
                    is_safe=True,
                    category=UrlPathCategory.DEEP_LINK,
                )
        except Exception as exc:
            return SsoRedirectValidation(
                target_url=trimmed,
                is_safe=False,
                category=UrlPathCategory.INVALID,
                reason=f"URL parsing failed: {exc}",
            )

        return SsoRedirectValidation(
            target_url=trimmed,
            is_safe=False,
            category=UrlPathCategory.INVALID,
            reason="Unrecognized or dangerous URL structure",
        )

    def build_sso_redirect_url(
        self,
        redirect_uri: str,
        sso_code: str,
        code_param: str = "sso_code",
    ) -> SsoRedirectBuildResult:
        """Strip existing sso_code parameters from redirect_uri and append the new one idempotently."""
        if not redirect_uri:
            return SsoRedirectBuildResult(
                original_url=redirect_uri,
                cleaned_url=redirect_uri,
                final_url=redirect_uri,
                code_attached=sso_code,
                is_relative=False,
            )

        trimmed = redirect_uri.strip()
        is_relative = self.is_same_origin_relative_path(trimmed)

        try:
            # Use a dummy scheme for relative paths to let urlsplit parse query params safely
            split_target = (
                trimmed if not is_relative else f"http://placeholder.local{trimmed}"
            )
            parts = urlsplit(split_target)

            # Strip existing code_param occurrences
            raw_query = parse_qsl(parts.query, keep_blank_values=True)
            filtered_query = [(k, v) for k, v in raw_query if k != code_param]

            # Reconstruct cleaned URL without code
            cleaned_query_str = urlencode(filtered_query)
            if is_relative:
                cleaned_parts = urlsplit(trimmed)
                cleaned_url = urlunsplit(
                    (
                        "",
                        "",
                        cleaned_parts.path,
                        cleaned_query_str,
                        cleaned_parts.fragment,
                    )
                )
            else:
                cleaned_url = urlunsplit(
                    (
                        parts.scheme,
                        parts.netloc,
                        parts.path,
                        cleaned_query_str,
                        parts.fragment,
                    )
                )

            # Append the new code
            filtered_query.append((code_param, sso_code))
            final_query_str = urlencode(filtered_query)

            if is_relative:
                cleaned_parts = urlsplit(trimmed)
                final_url = urlunsplit(
                    (
                        "",
                        "",
                        cleaned_parts.path,
                        final_query_str,
                        cleaned_parts.fragment,
                    )
                )
            else:
                final_url = urlunsplit(
                    (
                        parts.scheme,
                        parts.netloc,
                        parts.path,
                        final_query_str,
                        parts.fragment,
                    )
                )

            return SsoRedirectBuildResult(
                original_url=trimmed,
                cleaned_url=cleaned_url,
                final_url=final_url,
                code_attached=sso_code,
                is_relative=is_relative,
            )

        except Exception:
            # Fallback to minimal query separator append
            separator = "&" if "?" in trimmed else "?"
            encoded_code = quote(sso_code)
            fallback_final = f"{trimmed}{separator}{code_param}={encoded_code}"
            return SsoRedirectBuildResult(
                original_url=trimmed,
                cleaned_url=trimmed,
                final_url=fallback_final,
                code_attached=sso_code,
                is_relative=is_relative,
            )
