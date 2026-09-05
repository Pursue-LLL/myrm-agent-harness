"""Plugin packaging integrity validation (Harness framework layer).

Validates that static build artifacts and entrypoint scripts referenced by
stdio MCP servers actually exist within the plugin package (in-memory archive
file mapping).

This prevents catastrophic runtime Agent crashes caused by missing build
artifacts (e.g., third-party developers forgetting `npm run build` or omitting
`dist/` from the package zip).
"""

from __future__ import annotations

import posixpath
import re
from collections.abc import Collection
from dataclasses import dataclass, replace
from typing import Final

from .models import PluginDiagnostic, PluginDiagnosticLevel, PluginMcpServer

# Standard script interpreters that execute entrypoint scripts as arguments
_SCRIPT_INTERPRETERS: Final[frozenset[str]] = frozenset(
    {
        "node",
        "bun",
        "python",
        "python3",
        "bash",
        "sh",
        "deno",
        "ts-node",
    }
)

# Common dynamic argument flags whose following values should NOT be treated as entrypoints
_NON_ENTRYPOINT_FLAGS: Final[frozenset[str]] = frozenset(
    {
        "-o",
        "--output",
        "--output-dir",
        "--outDir",
        "-c",
        "--config",
        "-d",
        "--dir",
        "-e",
        "--eval",
        "-p",
        "--port",
        "-h",
        "--host",
        "-t",
        "--target",
        "-w",
        "--watch",
    }
)

_WINDOWS_SEP_RE: Final[re.Pattern[str]] = re.compile(r"\\+")


@dataclass(frozen=True)
class PackagingIntegrityVerdict:
    """Outcome of an artifact packaging integrity check."""

    is_valid: bool
    missing_path: str | None = None
    reason: str | None = None


def normalize_package_path(path: str) -> str:
    """Normalize relative path for package file lookup."""
    clean = _WINDOWS_SEP_RE.sub("/", path.strip())
    # Handle ${PLUGIN_ROOT}/ prefix
    if clean.startswith("${PLUGIN_ROOT}/"):
        clean = clean[len("${PLUGIN_ROOT}/") :]
    elif clean.startswith("${PLUGIN_DATA}/"):
        clean = clean[len("${PLUGIN_DATA}/") :]
    norm = posixpath.normpath(clean)
    if norm.startswith("./"):
        norm = norm[2:]
    return norm


def extract_server_entrypoint_path(server: PluginMcpServer) -> str | None:
    """Extract normalized entrypoint path from an MCP server, or None if not a local file."""
    if server.server_type != "stdio":
        return None

    cmd = (server.command or "").strip()
    if not cmd:
        return None

    # Case 1: Command itself is a local relative script (e.g. `./bin/cli.js` or `./dist/index.js`)
    if cmd.startswith("./") or cmd.startswith("${PLUGIN_ROOT}/"):
        return normalize_package_path(cmd)

    # Case 2: Command is a recognized script interpreter with arguments
    cmd_name = posixpath.basename(cmd)
    if cmd_name in _SCRIPT_INTERPRETERS and server.args:
        skip_next = False
        for arg in server.args:
            if skip_next:
                skip_next = False
                continue
            if arg in _NON_ENTRYPOINT_FLAGS:
                skip_next = True
                continue
            if arg.startswith("-"):
                continue
            # Found candidate entrypoint argument
            if arg.startswith("./") or arg.startswith("${PLUGIN_ROOT}/") or "/" in arg or "\\" in arg:
                return normalize_package_path(arg)
            # Standalone filename ending with standard script extension
            if any(arg.endswith(ext) for ext in (".js", ".mjs", ".cjs", ".ts", ".py", ".sh")):
                return normalize_package_path(arg)

    # Case 3: Check args for any explicit ./ relative paths regardless of interpreter
    if server.args:
        for arg in server.args:
            if arg.startswith("./") or arg.startswith("${PLUGIN_ROOT}/"):
                return normalize_package_path(arg)

    return None


def extract_server_raw_entrypoint(server: PluginMcpServer) -> str | None:
    """Extract raw entrypoint string (preserving leading ./ or ${PLUGIN_ROOT}/) from an MCP server."""
    if server.server_type != "stdio":
        return None

    cmd = (server.command or "").strip()
    if not cmd:
        return None

    if cmd.startswith("./") or cmd.startswith("${PLUGIN_ROOT}/"):
        return cmd

    cmd_name = posixpath.basename(cmd)
    if cmd_name in _SCRIPT_INTERPRETERS and server.args:
        skip_next = False
        for arg in server.args:
            if skip_next:
                skip_next = False
                continue
            if arg in _NON_ENTRYPOINT_FLAGS:
                skip_next = True
                continue
            if arg.startswith("-"):
                continue
            if arg.startswith("./") or arg.startswith("${PLUGIN_ROOT}/") or "/" in arg or "\\" in arg:
                return arg
            if any(arg.endswith(ext) for ext in (".js", ".mjs", ".cjs", ".ts", ".py", ".sh")):
                return arg

    if server.args:
        for arg in server.args:
            if arg.startswith("./") or arg.startswith("${PLUGIN_ROOT}/"):
                return arg

    return None


def verify_mcp_server_artifacts(
    server: PluginMcpServer,
    files: Collection[str],
    *,
    has_ts_sources: bool = False,
) -> tuple[bool, str | None, str | None]:
    """Verify that static artifacts referenced by a stdio server exist in the package.

    Returns:
        tuple[is_valid, missing_target_path, human_readable_reason]
    """
    entrypoint = extract_server_entrypoint_path(server)
    if entrypoint is None:
        # Non-stdio or purely global binary call (e.g. `docker run ...` or `python -m module`)
        return True, None, None

    # Exact existence in files
    normalized_files = {normalize_package_path(f) for f in files}
    if entrypoint in normalized_files:
        return True, None, None

    # Missing artifact detected
    if has_ts_sources and ("dist/" in entrypoint or "build/" in entrypoint or entrypoint.endswith(".js")):
        reason = (
            f"MCP server '{server.name}' requires build artifact '{entrypoint}', "
            f"but it is missing from the package zip. TypeScript sources exist; "
            f"did the author forget to run 'npm run build' before packaging?"
        )
    else:
        reason = (
            f"MCP server '{server.name}' references local entrypoint '{entrypoint}', "
            f"which does not exist in the plugin package."
        )

    return False, entrypoint, reason


def verify_mcp_server_packaging_integrity(
    server: PluginMcpServer,
    files: Collection[str],
    *,
    has_ts_sources: bool = False,
) -> PackagingIntegrityVerdict:
    """Wrapper returning a PackagingIntegrityVerdict dataclass."""
    is_valid, missing_path, reason = verify_mcp_server_artifacts(
        server, files, has_ts_sources=has_ts_sources
    )
    return PackagingIntegrityVerdict(
        is_valid=is_valid,
        missing_path=missing_path,
        reason=reason,
    )


def filter_valid_servers(
    servers: list[PluginMcpServer],
    files: Collection[str],
    diagnostics: list[PluginDiagnostic] | None = None,
) -> list[PluginMcpServer]:
    """Filter out servers with missing artifacts and append diagnostics if requested."""
    has_ts_sources = any(k.endswith((".ts", ".tsx")) for k in files)
    valid_servers: list[PluginMcpServer] = []

    for server in servers:
        is_valid, missing_path, reason = verify_mcp_server_artifacts(
            server, files, has_ts_sources=has_ts_sources
        )
        if not is_valid:
            if diagnostics is not None:
                diagnostics.append(
                    PluginDiagnostic(
                        component=f"mcp:{server.name}",
                        code="mcp_missing_artifact",
                        message=reason or f"Missing artifact '{missing_path}'",
                        level=PluginDiagnosticLevel.ERROR,
                    )
                )
        else:
            valid_servers.append(server)

    return valid_servers


def verify_plugin_packaging_integrity(
    servers: list[PluginMcpServer],
    files: Collection[str],
) -> tuple[list[PluginMcpServer], list[PluginDiagnostic]]:
    """Scan servers against package files, update runnability status, and record diagnostics."""
    has_ts_sources = any(k.endswith((".ts", ".tsx")) for k in files)
    processed_servers: list[PluginMcpServer] = []
    diagnostics: list[PluginDiagnostic] = []

    for server in servers:
        is_valid, missing_path, reason = verify_mcp_server_artifacts(
            server, files, has_ts_sources=has_ts_sources
        )
        if not is_valid:
            raw_entry = extract_server_raw_entrypoint(server) or missing_path or ""
            missing_tuple = (raw_entry,) if raw_entry else ()
            processed_servers.append(
                replace(
                    server,
                    is_runnable=False,
                    missing_artifacts=missing_tuple,
                    missing_artifact=raw_entry or None,
                )
            )
            diagnostics.append(
                PluginDiagnostic(
                    component=f"mcp:{server.name}",
                    code="mcp_missing_artifact",
                    message=reason or f"Missing artifact '{missing_path}'",
                    level=PluginDiagnosticLevel.ERROR,
                )
            )
        else:
            processed_servers.append(
                replace(
                    server,
                    is_runnable=True,
                    missing_artifacts=(),
                    missing_artifact=None,
                )
            )

    return processed_servers, diagnostics
