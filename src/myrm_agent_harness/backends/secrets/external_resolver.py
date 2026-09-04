"""External secret reference resolver for 1Password and Bitwarden.

[INPUT]
- None (standard library only)

[OUTPUT]
- is_external_secret_reference: Helper to test whether a value is an op:// or bw:// URI
- resolve_external_secret: Resolves op:// or bw:// reference dynamically via local CLI
- ExternalSecretResolutionError: Raised on resolution failure or timeout

[POS]
Harness backends/secrets/ layer. Implements Zero-Disk Plaintext resolution
for 1Password (op read) and Bitwarden (bw get password / bws secret get) URIs.
"""

from __future__ import annotations

import logging
import re
import subprocess

logger = logging.getLogger(__name__)

_OP_URI_PATTERN = re.compile(r"^op://[a-zA-Z0-9_\-\.\s]+/[a-zA-Z0-9_\-\.\s]+/[a-zA-Z0-9_\-\.\s]+$")
_BW_URI_PREFIXES = ("bw://", "bws://")


class ExternalSecretResolutionError(Exception):
    """Raised when an external secret URI fails to resolve or times out."""

    pass


def is_external_secret_reference(value: str | None) -> bool:
    """Return True if the given string represents an external secret URI."""
    if not value or not isinstance(value, str):
        return False
    trimmed = value.strip()
    if (trimmed.startswith('"') and trimmed.endswith('"')) or (trimmed.startswith("'") and trimmed.endswith("'")):
        trimmed = trimmed[1:-1].strip()
    return trimmed.startswith("op://") or trimmed.startswith(_BW_URI_PREFIXES)


def resolve_external_secret(
    reference: str,
    timeout_seconds: float = 6.0,
) -> str:
    """Resolve an external secret reference to its plaintext value in memory.

    Supported schemes:
    - op://<vault>/<item>/<field> or op://<item>/<field>: Invokes `op read "<reference>"`
    - bw://<item_id_or_name>: Invokes `bw get password "<item>"`
    - bws://<secret_id>: Invokes `bws secret get "<secret_id>" --output json`

    Args:
        reference: The secret URI (e.g., 'op://Private/OpenAI/credential')
        timeout_seconds: Max execution time before fail-safe timeout (default 6.0s)

    Returns:
        The resolved plaintext secret string.

    Raises:
        ExternalSecretResolutionError: If the CLI returns non-zero, is missing, or times out.
    """
    ref = reference.strip()
    if (ref.startswith('"') and ref.endswith('"')) or (ref.startswith("'") and ref.endswith("'")):
        ref = ref[1:-1].strip()

    if ref.startswith("op://"):
        cmd = ["op", "read", ref]
    elif ref.startswith("bw://"):
        item_target = ref[len("bw://") :].strip()
        cmd = ["bw", "get", "password", item_target]
    elif ref.startswith("bws://"):
        secret_id = ref[len("bws://") :].strip()
        cmd = ["bws", "secret", "get", secret_id, "--output", "json"]
    else:
        raise ExternalSecretResolutionError(f"Unsupported external secret URI scheme: {reference}")

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
        if proc.returncode != 0:
            err_msg = proc.stderr.strip()[:200] or f"Exit code {proc.returncode}"
            logger.warning("External secret CLI (%s) failed: %s", cmd[0], err_msg)
            raise ExternalSecretResolutionError(f"Failed to resolve secret with {cmd[0]}: {err_msg}")

        output = proc.stdout.strip()
        if ref.startswith("bws://"):
            import json

            try:
                data = json.loads(output)
                if isinstance(data, dict) and "value" in data:
                    return str(data["value"]).strip()
            except Exception as e:
                raise ExternalSecretResolutionError(f"Failed to parse bws JSON output: {e}") from e

        if not output:
            raise ExternalSecretResolutionError(f"External secret CLI returned empty value for: {reference}")
        return output

    except subprocess.TimeoutExpired as exc:
        logger.error("External secret CLI (%s) timed out (%.1fs)", cmd[0], timeout_seconds)
        raise ExternalSecretResolutionError(
            f"External secret resolution timed out ({timeout_seconds}s) for: {reference}"
        ) from exc
    except FileNotFoundError as exc:
        raise ExternalSecretResolutionError(
            f"CLI '{cmd[0]}' is not installed or not found in system PATH."
        ) from exc
    except Exception as exc:
        if isinstance(exc, ExternalSecretResolutionError):
            raise
        logger.error("Unexpected error resolving external secret: %s", exc)
        raise ExternalSecretResolutionError(f"Failed to resolve external secret: {exc}") from exc
