"""PEP 578 Audit Hook for Sandbox Security.

[INPUT]
- (none)

[OUTPUT]
- install: function — install
- get_audit_hook_source_code: function — returns self-contained source string for inlining
- SecurityError: Exception class

[POS]
PEP 578 Audit Hook. Provides C-level interception of dangerous operations (network, fs, process, memory) to prevent LLM code escapes.
"""

import os
import sys


class SecurityError(Exception):
    """Exception raised when a security violation is detected by the PEP 578 Audit Hook."""

    pass


def install(
    workspace_path: str,
    allow_network: bool = False,
    allowed_hosts: frozenset[str] | None = None,
    readonly_workspace: bool = False,
) -> None:
    """Install the audit hook. This function should only be called once per process.

    Args:
        workspace_path: The absolute path to the allowed workspace.
        allow_network: Whether to allow AF_INET network access.
        allowed_hosts: Allowed hosts if network is allowed.
        readonly_workspace: Whether the workspace is strictly read-only.
    """
    workspace_real = os.path.realpath(workspace_path)

    # We must allow writes to the system temp directory so standard libraries (like pytest) don't break.
    import tempfile

    tmpdir_real = os.path.realpath(tempfile.gettempdir())

    # Also explicitly allow the workspace's local .tmp if configured and not in readonly mode
    workspace_tmp = os.path.realpath(os.path.join(workspace_real, ".tmp"))

    # Disallow ctypes globally to prevent C-level escape.
    sys.modules["ctypes"] = None
    sys.modules["_ctypes"] = None

    def audit_hook(event: str, args: tuple) -> None:
        # 1. Process / Command Execution
        if event in (
            "os.system",
            "os.exec",
            "os.posix_spawn",
            "os.spawn",
            "subprocess.Popen",
        ):
            raise SecurityError(f"Subprocess execution is strictly forbidden in the sandbox. Event: {event}")

        # 2. Memory / C-extension Escape (fallback if ctypes import block is bypassed)
        if event == "ctypes.dlopen":
            raise SecurityError("Dynamic library loading (ctypes) is strictly forbidden.")

        # 3. Network Isolation (TCP connect, UDP send, port bind)
        if event in ("socket.connect", "socket.bind", "socket.sendto", "socket.sendmsg"):
            # CPython audit event signature for socket: (self, address) or (self, data, [flags], address)
            # Find the target address tuple/str regardless of whether args comes from real runtime or mock
            address = None
            if args:
                for item in reversed(args):
                    if isinstance(item, (str, tuple)):
                        address = item
                        break

            if not allow_network:
                # AF_UNIX sockets use a string address (for IPC). We allow them for MCP IPC even if network is False.
                if isinstance(address, str):
                    return
                raise SecurityError("Network access is blocked by sandbox policy.")

            if event == "socket.connect":
                # AF_UNIX sockets use a string address (for IPC). We allow them for MCP IPC.
                if isinstance(address, tuple) and allowed_hosts is not None:
                    host = address[0]
                    if host not in allowed_hosts:
                        raise SecurityError(
                            f"Network access to '{host}' is blocked. Allowed hosts: {', '.join(allowed_hosts)}"
                        )

        # 4. File System Isolation
        destructive_events = {
            "os.remove",
            "os.rmdir",
            "os.mkdir",
            "os.chmod",
            "os.chown",
            "os.unlink",
            "os.truncate",
        }
        rename_events = {"os.rename", "os.replace", "os.link", "os.symlink"}

        if event in destructive_events or event in rename_events:
            paths_to_check = [args[0]]
            if event in rename_events and len(args) > 1:
                paths_to_check.append(args[1])

            for p in paths_to_check:
                try:
                    resolved_path = os.path.realpath(str(p))
                except Exception:
                    resolved_path = str(p)

                # If readonly_workspace is enabled, writes are blocked in workspace as well
                if readonly_workspace and (
                    resolved_path.startswith(workspace_real) or resolved_path.startswith(workspace_tmp)
                ):
                    raise SecurityError(
                        f"Destructive file operation ({event}) in workspace blocked by readonly_workspace policy: {resolved_path}"
                    )

                # Destructive operations are ONLY allowed in workspace/temp
                if not (
                    resolved_path.startswith(workspace_real)
                    or resolved_path.startswith(tmpdir_real)
                    or resolved_path.startswith(workspace_tmp)
                ):
                    raise SecurityError(
                        f"Destructive file operation ({event}) outside allowed workspace blocked: {resolved_path}"
                    )

        if event == "open":
            path, mode, flags = args
            # We strictly restrict WRITE operations to prevent destruction.
            # mode is a string like 'r', 'w', 'a', '+', 'x'
            # flags is the integer flag (e.g. os.O_RDWR)

            is_write = False
            if isinstance(mode, str):
                is_write = any(m in mode for m in ("w", "a", "+", "x"))
            elif isinstance(flags, int):
                # O_WRONLY = 1, O_RDWR = 2, O_CREAT = 64 (0o100), O_APPEND = 1024 (0o2000)
                is_write = (flags & os.O_WRONLY) or (flags & os.O_RDWR) or (flags & os.O_CREAT) or (flags & os.O_APPEND)

            if is_write:
                try:
                    resolved_path = os.path.realpath(str(path))
                except Exception:
                    resolved_path = str(path)

                # If readonly_workspace is enabled, writes inside workspace are blocked
                if readonly_workspace and (
                    resolved_path.startswith(workspace_real) or resolved_path.startswith(workspace_tmp)
                ):
                    raise SecurityError(
                        f"Write operation inside workspace blocked by readonly_workspace policy: {resolved_path}"
                    )

                # Allow writes to workspace, system temp, and workspace temp
                # Exception for standard pipes
                if not (
                    resolved_path.startswith(workspace_real)
                    or resolved_path.startswith(tmpdir_real)
                    or resolved_path.startswith(workspace_tmp)
                ) and resolved_path not in ("/dev/null", "/dev/stdout", "/dev/stderr"):
                    raise SecurityError(f"Write operation outside allowed workspace blocked: {resolved_path}")

            else:
                # Read operation restrictions (prevent reading sensitive system files outside workspace)
                try:
                    resolved_path = os.path.realpath(str(path))
                except Exception:
                    resolved_path = str(path)

                # Credential shield: block reading sensitive developer credentials outside workspace
                if not resolved_path.startswith(workspace_real):
                    sensitive_keywords = [
                        "/.ssh/",
                        "/.aws/",
                        "/.kube/",
                        "/.git-credentials",
                        "/.docker/config.json",
                        "/.netrc",
                        "/etc/shadow",
                        "/etc/passwd",
                    ]
                    if any(kw in resolved_path for kw in sensitive_keywords):
                        raise SecurityError(f"Read access to sensitive file blocked: {resolved_path}")

    sys.addaudithook(audit_hook)


def get_audit_hook_source_code() -> str:
    """Return self-contained PEP 578 audit hook implementation code for inlining in execution wrappers.

    Single Source of Truth (SSOT): Any updates to audit hook policies should be reflected here.
    """
    import inspect

    hook_lines, _ = inspect.getsourcelines(install)
    # Strip the def install line and outer indentation so it can be called or defined directly
    install_source = inspect.getsource(install)
    error_source = inspect.getsource(SecurityError)

    return f"{error_source}\n\n{install_source}\n"

