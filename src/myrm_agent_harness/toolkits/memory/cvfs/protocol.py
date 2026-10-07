"""[POS]: src/myrm_agent_harness/toolkits/memory/cvfs/protocol.py
[INPUT]: Raw URI strings and path references for Context Virtual File System.
[OUTPUT]: CVFSProtocol parsing, normalizing, and validating canonical ctx:// URIs.
"""

import posixpath
import re

PRIMARY_SCHEME = "context://"
COMPAT_SCHEME = "ctx://"
SCHEME_PREFIX = "ctx://"  # Preserved for backward compatibility
ALLOWED_SCHEMES = (PRIMARY_SCHEME, COMPAT_SCHEME)
ALLOWED_TOP_NAMESPACES = ("memories", "skills", "resources", "user", "artifacts")


class CVFSProtocolError(ValueError):
    """Raised when a URI violates the Context Virtual File System protocol."""


class CVFSProtocol:
    """Protocol helper for canonical context:// and ctx:// URI parsing and validation."""

    @classmethod
    def extract_scheme(cls, uri: str) -> tuple[str, str]:
        """Extract scheme prefix and path part from raw URI string."""
        clean = uri.strip()
        if clean.startswith(PRIMARY_SCHEME):
            return PRIMARY_SCHEME, clean[len(PRIMARY_SCHEME):]
        if clean.startswith("context:/"):
            return PRIMARY_SCHEME, clean[len("context:/"):].lstrip("/")
        if clean.startswith(COMPAT_SCHEME):
            return COMPAT_SCHEME, clean[len(COMPAT_SCHEME):]
        if clean.startswith("ctx:/"):
            return COMPAT_SCHEME, clean[len("ctx:/"):].lstrip("/")
        if clean.startswith("/"):
            return COMPAT_SCHEME, clean.lstrip("/")
        return COMPAT_SCHEME, clean

    @classmethod
    def normalize_uri(cls, uri: str, prefer_primary: bool = False) -> str:
        """Normalize context URI to canonical form, preventing directory traversal."""
        scheme, path_part = cls.extract_scheme(uri)
        target_scheme = PRIMARY_SCHEME if prefer_primary else scheme

        # Disallow directory traversal
        if ".." in path_part.split("/"):
            raise CVFSProtocolError(f"Directory traversal detected in URI: {uri}")

        # Normalize with POSIX conventions
        normalized_path = posixpath.normpath("/" + path_part).lstrip("/")
        if not normalized_path or normalized_path == ".":
            return target_scheme

        return f"{target_scheme}{normalized_path}"

    @classmethod
    def to_canonical_uri(cls, uri: str) -> str:
        """Convert any supported URI format to primary context:// canonical format."""
        return cls.normalize_uri(uri, prefer_primary=True)

    @classmethod
    def split_uri(cls, uri: str) -> list[str]:
        """Split URI path components into discrete segments."""
        _, path_part = cls.extract_scheme(uri)
        # Disallow directory traversal
        if ".." in path_part.split("/"):
            raise CVFSProtocolError(f"Directory traversal detected in URI: {uri}")
        normalized_path = posixpath.normpath("/" + path_part).lstrip("/")
        if not normalized_path or normalized_path == ".":
            return []
        return normalized_path.split("/")

    @classmethod
    def get_parent_uri(cls, uri: str) -> str:
        """Derive parent directory URI preserving original scheme."""
        scheme, _ = cls.extract_scheme(uri)
        norm = cls.normalize_uri(uri)
        if norm in (PRIMARY_SCHEME, COMPAT_SCHEME):
            return norm
        segments = cls.split_uri(norm)
        if len(segments) <= 1:
            return scheme
        parent_path = "/".join(segments[:-1])
        return f"{scheme}{parent_path}"

    @classmethod
    def get_basename(cls, uri: str) -> str:
        """Extract final file or directory name."""
        norm = cls.normalize_uri(uri)
        if norm in (PRIMARY_SCHEME, COMPAT_SCHEME):
            return ""
        segments = cls.split_uri(norm)
        return segments[-1] if segments else ""

    @classmethod
    def validate_namespace(cls, uri: str) -> None:
        """Validate that URI conforms to supported top-level namespaces."""
        segments = cls.split_uri(uri)
        if not segments:
            return
        top = segments[0]
        if top not in ALLOWED_TOP_NAMESPACES:
            allowed = ", ".join(ALLOWED_TOP_NAMESPACES)
            raise CVFSProtocolError(
                f"Invalid top-level namespace '{top}'. Allowed namespaces: {allowed}"
            )

    @classmethod
    def is_valid_name(cls, name: str) -> bool:
        """Check if node name contains only safe alphanumeric and standard punctuation."""
        return bool(re.match(r"^[a-zA-Z0-9_\-\.]{1,128}$", name))
