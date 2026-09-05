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

from .models import PluginCapabilityTier, PluginDiagnostic, PluginDiagnosticLevel, PluginMcpServer

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
    # Strip macro placeholders
    if clean.startswith("${PLUGIN_ROOT}/"):
        clean = clean[len("${PLUGIN_ROOT}/") :]
    elif clean.startswith("${PLUGIN_DATA}/"):
        clean = clean[len("${PLUGIN_DATA}/") :]
    norm = posixpath.normpath(clean)
    if norm.startswith("./"):
        norm = norm[2:]
    return norm


def extract_server_raw_entrypoint(server: PluginMcpServer) -> str | None:
    """Extract raw entrypoint string as declared in command or args."""
    if server.server_type != "stdio":
        return None

    cmd = (server.command or "").strip()
    if not cmd:
        return None

    if cmd.startswith("./") or cmd.startswith("${PLUGIN_ROOT}"):
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
            if arg.startswith("./") or arg.startswith("${PLUGIN_ROOT}") or "/" in arg or "\\" in arg:
                return arg
            if any(arg.endswith(ext) for ext in (".js", ".mjs", ".cjs", ".ts", ".py", ".sh")):
                return arg

    if server.args:
        for arg in server.args:
            if arg.startswith("./") or arg.startswith("${PLUGIN_ROOT}"):
                return arg

    return None


def extract_server_entrypoint_path(server: PluginMcpServer) -> str | None:
    """Extract normalized entrypoint path from an MCP server, or None if not a local file."""
    raw = extract_server_raw_entrypoint(server)
    if raw is None:
        return None
    return normalize_package_path(raw)


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
        return True, None, None

    normalized_files = {normalize_package_path(f) for f in files}
    if entrypoint in normalized_files:
        return True, None, None

    # Check for typescript/build indicators
    ts_indicated = has_ts_sources or any(f.endswith((".ts", ".tsx")) for f in normalized_files)
    if ts_indicated and ("dist/" in entrypoint or "out/" in entrypoint or entrypoint.endswith(".js")):
        reason = (
            f"MCP server '{server.name}' requires build artifact '{entrypoint}', "
            f"which is missing from the package zip. TypeScript sources exist; "
            f"run 'npm run build' before packaging."
        )
    else:
        reason = (
            f"MCP server '{server.name}' references local entrypoint '{entrypoint}', "
            f"which does not exist in the plugin package. Ensure the project is built (e.g. 'npm run build') and artifacts are packaged."
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


def verify_plugin_packaging_integrity(
    arg1: Collection[str] | list[PluginMcpServer],
    arg2: Collection[str] | list[PluginMcpServer],
) -> tuple[list[PluginMcpServer], list[PluginDiagnostic]]:
    """Scan servers against package files, update runnability, and generate diagnostics.

    Supports both (files, servers) and (servers, files) signatures for caller ergonomics.
    """
    if isinstance(arg1, list) and (not arg1 or isinstance(arg1[0], PluginMcpServer)):
        servers = arg1
        files = arg2  # type: ignore[assignment]
    else:
        files = arg1  # type: ignore[assignment]
        servers = arg2  # type: ignore[assignment]

    file_keys = set(files.keys()) if isinstance(files, dict) else set(files)
    has_ts_sources = any(k.endswith((".ts", ".tsx")) for k in file_keys)

    verified_servers: list[PluginMcpServer] = []
    diagnostics: list[PluginDiagnostic] = []

    for server in servers:
        is_valid, missing_path, reason = verify_mcp_server_artifacts(
            server, file_keys, has_ts_sources=has_ts_sources
        )
        if is_valid:
            verified_servers.append(
                replace(
                    server,
                    is_runnable=True,
                    missing_artifacts=(),
                    missing_artifact=None,
                )
            )
        else:
            raw_entry = extract_server_raw_entrypoint(server)
            missing_candidates = [x for x in (raw_entry, missing_path) if x]
            missing_tuple = tuple(dict.fromkeys(missing_candidates))
            verified_servers.append(
                replace(
                    server,
                    is_runnable=False,
                    missing_artifacts=missing_tuple,
                    missing_artifact=missing_path,
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

    return verified_servers, diagnostics


def filter_valid_servers(
    servers: list[PluginMcpServer],
    files: Collection[str],
    diagnostics: list[PluginDiagnostic] | None = None,
) -> list[PluginMcpServer]:
    """Filter out servers with missing artifacts and append diagnostics if requested.

    When `diagnostics` list is passed explicitly, appends to it and returns valid servers list.
    When `diagnostics` is None, returns (valid_servers, diagnostics) tuple.
    """
    verified, diags = verify_plugin_packaging_integrity(servers, files)
    valid_servers = [s for s in verified if s.is_runnable]
    if diagnostics is not None:
        diagnostics.extend(diags)
        return valid_servers
    return valid_servers, diags


def infer_server_capabilities(server: PluginMcpServer) -> tuple[PluginCapabilityTier, ...]:
    """Statically infer the sandbox capability tier for an MCP server entry.

    Heuristics:
    1. Declared server capabilities are always preserved.
    2. Remote transports (streamable_http, sse) require NETWORK capability.
    3. Local stdio transport spawns child processes, thus requiring SHELL_EXEC, FS_READ, FS_WRITE.
    4. Commands executing compilers, package managers, or explicit shell scripts also flag DESTRUCTIVE if dangerous.
    """
    from .models import PluginCapabilityTier

    caps: set[PluginCapabilityTier] = set(server.capabilities)

    if server.server_type in ("streamable_http", "sse"):
        caps.add(PluginCapabilityTier.NETWORK)
    elif server.server_type == "stdio":
        caps.add(PluginCapabilityTier.SHELL_EXEC)
        caps.add(PluginCapabilityTier.FS_WRITE)
        caps.add(PluginCapabilityTier.FS_READ)

        # Inspect command for dangerous/destructive interpreters or root scripts
        cmd = (server.command or "").strip().lower()
        if cmd in ("bash", "sh", "zsh", "sudo") or any(
            arg in ("-c", "rm", "dd", "mkfs") for arg in (server.args or [])
        ):
            caps.add(PluginCapabilityTier.DESTRUCTIVE)

    if not caps:
        caps.add(PluginCapabilityTier.READ_ONLY)

    return tuple(sorted(caps, key=lambda c: c.value))


def verify_plugin_capability_diff(
    declared_caps: Collection[PluginCapabilityTier],
    servers: Collection[PluginMcpServer],
) -> list[PluginDiagnostic]:
    """Audit declared capabilities against inferred server capabilities.

    If declared_caps is empty (manifest did not specify capabilities), no diff
    violation is raised (backwards-compatible with unannotated plugins).

    When declared_caps is explicitly specified, verifies whether any server
    requires capabilities outside the declared set.
    For any undeclared capability, records a structured diagnostic:
      - Level ERROR if DESTRUCTIVE or SHELL_EXEC is undeclared (high security threat).
      - Level WARNING for other undeclared capabilities (NETWORK, FS_WRITE, FS_READ).
    """
    if not declared_caps:
        return []

    declared_set = frozenset(declared_caps)
    diagnostics: list[PluginDiagnostic] = []

    for server in servers:
        server_caps = frozenset(server.capabilities)
        undeclared = server_caps - declared_set
        # READ_ONLY is a subset of all capabilities, so having READ_ONLY is never an escalation
        undeclared = {c for c in undeclared if c != PluginCapabilityTier.READ_ONLY}

        if undeclared:
            sorted_undeclared = sorted(undeclared, key=lambda c: c.value)
            is_high_risk = any(
                c in (PluginCapabilityTier.DESTRUCTIVE, PluginCapabilityTier.SHELL_EXEC)
                for c in undeclared
            )
            level = (
                PluginDiagnosticLevel.ERROR
                if is_high_risk
                else PluginDiagnosticLevel.WARNING
            )
            cap_names = ", ".join(c.value for c in sorted_undeclared)
            declared_names = (
                ", ".join(c.value for c in sorted(declared_set, key=lambda c: c.value))
                or "none"
            )
            diagnostics.append(
                PluginDiagnostic(
                    component=f"mcp:{server.name}",
                    code="capability_undeclared_privilege",
                    message=(
                        f"MCP server '{server.name}' requires undeclared capability ({cap_names}). "
                        f"Plugin manifest only declared: [{declared_names}]."
                    ),
                    level=level,
                )
            )

    return diagnostics


