"""[POS]: src/myrm_agent_harness/toolkits/memory/cvfs/protocol.py
[INPUT]: Raw URI strings and path references for Context Virtual File System.
[OUTPUT]: CVFSProtocol parsing, normalizing, and validating canonical ctx:// URIs.
"""

import posixpath
import re

SCHEME_PREFIX = "ctx://"
ALLOWED_TOP_NAMESPACES = ("resources", "user", "artifacts")


class CVFSProtocolError(ValueError):
    """Raised when a URI violates the Context Virtual File System protocol."""


class CVFSProtocol:
    """Protocol helper for canonical ctx:// URI parsing and validation."""

    @classmethod
    def normalize_uri(cls, uri: str) -> str:
        """Normalize ctx:// URI to canonical form, preventing directory traversal."""
        clean = uri.strip()
        if not clean.startswith(SCHEME_PREFIX):
            if clean.startswith("ctx:/"):
                clean = SCHEME_PREFIX + clean[5:].lstrip("/")
            elif clean.startswith("/"):
                clean = SCHEME_PREFIX + clean.lstrip("/")
            else:
                clean = SCHEME_PREFIX + clean

        path_part = clean[len(SCHEME_PREFIX):]
        # Disallow directory traversal
        if ".." in path_part.split("/"):
            raise CVFSProtocolError(f"Directory traversal detected in URI: {uri}")

        # Normalize with POSIX conventions
        normalized_path = posixpath.normpath("/" + path_part).lstrip("/")
        if not normalized_path or normalized_path == ".":
            return SCHEME_PREFIX

        return f"{SCHEME_PREFIX}{normalized_path}"

    @classmethod
    def split_uri(cls, uri: str) -> list[str]:
        """Split URI path components into discrete segments."""
        norm = cls.normalize_uri(uri)
        path_part = norm[len(SCHEME_PREFIX):].strip("/")
        if not path_part:
            return []
        return path_part.split("/")

    @classmethod
    def get_parent_uri(cls, uri: str) -> str:
        """Derive parent directory URI."""
        norm = cls.normalize_uri(uri)
        if norm == SCHEME_PREFIX:
            return SCHEME_PREFIX
        segments = cls.split_uri(norm)
        if len(segments) <= 1:
            return SCHEME_PREFIX
        parent_path = "/".join(segments[:-1])
        return f"{SCHEME_PREFIX}{parent_path}"

    @classmethod
    def get_basename(cls, uri: str) -> str:
        """Extract final file or directory name."""
        norm = cls.normalize_uri(uri)
        if norm == SCHEME_PREFIX:
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
