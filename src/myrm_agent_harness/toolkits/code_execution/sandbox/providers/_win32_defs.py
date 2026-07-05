"""Win32 ctypes structures and low-level API helpers for AppContainer sandbox.

Internal module — only imported by appcontainer.py on Windows.

[INPUT]  (none — pure Win32 type definitions and API wrappers)
[OUTPUT] Structures, constants, and helper functions for AppContainer Win32 calls.
[POS]    Win32 API foundation layer for the AppContainer provider.
"""

from __future__ import annotations

import asyncio
import ctypes
import os
import sys
from typing import Any

if sys.platform == "win32":
    import ctypes.wintypes
else:
    # Provide minimal stubs for type definitions on non-Windows (test/lint only)
    class _WintypesStub:
        DWORD = ctypes.c_ulong
        HANDLE = ctypes.c_void_p
        WORD = ctypes.c_ushort
        BYTE = ctypes.c_ubyte
        LPWSTR = ctypes.c_wchar_p
        BOOL = ctypes.c_int

    ctypes.wintypes = _WintypesStub  # type: ignore[attr-defined]

from myrm_agent_harness.toolkits.code_execution.sandbox.sandbox_types import (
    SandboxPolicy,
)

# --- Win32 constants ---

EXTENDED_STARTUPINFO_PRESENT = 0x00080000
CREATE_UNICODE_ENVIRONMENT = 0x00000400
CREATE_NO_WINDOW = 0x08000000
PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES = 0x00020009
STARTF_USESTDHANDLES = 0x00000100
HANDLE_FLAG_INHERIT = 0x00000001

CAP_INTERNET_CLIENT = "S-1-15-3-1"
CAP_INTERNET_CLIENT_SERVER = "S-1-15-3-2"
CAP_PRIVATE_NETWORK = "S-1-15-3-3"


# --- ctypes structures ---


class SID_AND_ATTRIBUTES(ctypes.Structure):
    _fields_ = [
        ("Sid", ctypes.c_void_p),
        ("Attributes", ctypes.wintypes.DWORD),
    ]


class SECURITY_CAPABILITIES(ctypes.Structure):
    _fields_ = [
        ("AppContainerSid", ctypes.c_void_p),
        ("Capabilities", ctypes.POINTER(SID_AND_ATTRIBUTES)),
        ("CapabilityCount", ctypes.wintypes.DWORD),
        ("Reserved", ctypes.wintypes.DWORD),
    ]


class STARTUPINFOW(ctypes.Structure):
    _fields_ = [
        ("cb", ctypes.wintypes.DWORD),
        ("lpReserved", ctypes.wintypes.LPWSTR),
        ("lpDesktop", ctypes.wintypes.LPWSTR),
        ("lpTitle", ctypes.wintypes.LPWSTR),
        ("dwX", ctypes.wintypes.DWORD),
        ("dwY", ctypes.wintypes.DWORD),
        ("dwXSize", ctypes.wintypes.DWORD),
        ("dwYSize", ctypes.wintypes.DWORD),
        ("dwXCountChars", ctypes.wintypes.DWORD),
        ("dwYCountChars", ctypes.wintypes.DWORD),
        ("dwFillAttribute", ctypes.wintypes.DWORD),
        ("dwFlags", ctypes.wintypes.DWORD),
        ("wShowWindow", ctypes.wintypes.WORD),
        ("cbReserved2", ctypes.wintypes.WORD),
        ("lpReserved2", ctypes.c_void_p),
        ("hStdInput", ctypes.wintypes.HANDLE),
        ("hStdOutput", ctypes.wintypes.HANDLE),
        ("hStdError", ctypes.wintypes.HANDLE),
    ]


class STARTUPINFOEXW(ctypes.Structure):
    _fields_ = [
        ("StartupInfo", STARTUPINFOW),
        ("lpAttributeList", ctypes.c_void_p),
    ]


class PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("hProcess", ctypes.wintypes.HANDLE),
        ("hThread", ctypes.wintypes.HANDLE),
        ("dwProcessId", ctypes.wintypes.DWORD),
        ("dwThreadId", ctypes.wintypes.DWORD),
    ]


# --- SID helpers ---


def string_to_sid(sid_string: str) -> ctypes.c_void_p:
    """Convert SID string to binary SID."""
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)  # type: ignore[attr-defined]
    psid = ctypes.c_void_p()
    if not advapi32.ConvertStringSidToSidW(sid_string, ctypes.byref(psid)):
        raise OSError(f"ConvertStringSidToSidW failed for {sid_string}")
    return psid


def sid_to_string(psid: ctypes.c_void_p) -> str:
    """Convert binary SID to string."""
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)  # type: ignore[attr-defined]
    str_sid = ctypes.wintypes.LPWSTR()
    if not advapi32.ConvertSidToStringSidW(psid, ctypes.byref(str_sid)):
        raise OSError("ConvertSidToStringSidW failed")
    result = str_sid.value or ""
    ctypes.WinDLL("kernel32", use_last_error=True).LocalFree(str_sid)  # type: ignore[attr-defined]
    return result


# --- Profile management ---


def create_appcontainer_profile(name: str) -> str:
    """Create AppContainer profile, return SID string. Reuses if exists."""
    userenv = ctypes.WinDLL("userenv", use_last_error=True)  # type: ignore[attr-defined]
    psid = ctypes.c_void_p()
    hr = userenv.CreateAppContainerProfile(
        name,
        name,
        f"Myrm Agent Sandbox ({name})",
        None,
        0,
        ctypes.byref(psid),
    )
    if hr == -2147023649:  # HRESULT_ERROR_ALREADY_EXISTS (0x800700B7)
        psid = ctypes.c_void_p()
        hr2 = userenv.DeriveAppContainerSidFromAppContainerName(name, ctypes.byref(psid))
        if hr2 != 0:
            raise OSError(f"DeriveAppContainerSidFromAppContainerName failed: 0x{hr2 & 0xFFFFFFFF:08X}")
    elif hr != 0:
        raise OSError(f"CreateAppContainerProfile failed: 0x{hr & 0xFFFFFFFF:08X}")

    sid_str = sid_to_string(psid)
    ctypes.WinDLL("ole32", use_last_error=True).CoTaskMemFree(psid)  # type: ignore[attr-defined]
    return sid_str


def delete_appcontainer_profile(name: str) -> bool:
    """Delete AppContainer profile. Returns True if deleted."""
    try:
        userenv = ctypes.WinDLL("userenv", use_last_error=True)  # type: ignore[attr-defined]
        hr = userenv.DeleteAppContainerProfile(name)
        return hr == 0
    except OSError:
        return False


# --- Process creation helpers ---


def create_pipe(
    kernel32: Any, *, inherit_read: bool
) -> tuple[ctypes.wintypes.HANDLE, ctypes.wintypes.HANDLE]:
    """Create an inheritable pipe pair."""
    read_handle = ctypes.wintypes.HANDLE()
    write_handle = ctypes.wintypes.HANDLE()

    class _SA(ctypes.Structure):
        _fields_ = [
            ("nLength", ctypes.wintypes.DWORD),
            ("lpSecurityDescriptor", ctypes.c_void_p),
            ("bInheritHandle", ctypes.wintypes.BOOL),
        ]

    sa = _SA()
    sa.nLength = ctypes.sizeof(sa)
    sa.lpSecurityDescriptor = None
    sa.bInheritHandle = True

    if not kernel32.CreatePipe(
        ctypes.byref(read_handle), ctypes.byref(write_handle), ctypes.byref(sa), 0
    ):
        raise OSError("CreatePipe failed")

    if inherit_read:
        kernel32.SetHandleInformation(write_handle, HANDLE_FLAG_INHERIT, 0)
    else:
        kernel32.SetHandleInformation(read_handle, HANDLE_FLAG_INHERIT, 0)

    return read_handle, write_handle


def build_capabilities(
    policy: SandboxPolicy,
) -> tuple[list[ctypes.c_void_p], ctypes.POINTER(SID_AND_ATTRIBUTES) | None]:
    """Build capability SIDs based on network policy."""
    cap_sids: list[ctypes.c_void_p] = []

    if policy.allow_network:
        cap_sids.append(string_to_sid(CAP_INTERNET_CLIENT))
        cap_sids.append(string_to_sid(CAP_INTERNET_CLIENT_SERVER))
        cap_sids.append(string_to_sid(CAP_PRIVATE_NETWORK))

    if not cap_sids:
        return cap_sids, None

    array_type = SID_AND_ATTRIBUTES * len(cap_sids)
    cap_array = array_type()
    for i, psid in enumerate(cap_sids):
        cap_array[i].Sid = psid
        cap_array[i].Attributes = 4  # SE_GROUP_ENABLED

    return cap_sids, ctypes.cast(cap_array, ctypes.POINTER(SID_AND_ATTRIBUTES))


def create_attribute_list(
    kernel32: Any, sec_cap: SECURITY_CAPABILITIES
) -> ctypes.c_void_p:
    """Create process thread attribute list with security capabilities."""
    size = ctypes.c_size_t(0)
    kernel32.InitializeProcThreadAttributeList(None, 1, 0, ctypes.byref(size))

    attr_list = ctypes.create_string_buffer(size.value)
    if not kernel32.InitializeProcThreadAttributeList(attr_list, 1, 0, ctypes.byref(size)):
        raise OSError("InitializeProcThreadAttributeList failed")

    if not kernel32.UpdateProcThreadAttribute(
        attr_list,
        0,
        PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES,
        ctypes.byref(sec_cap),
        ctypes.sizeof(sec_cap),
        None,
        None,
    ):
        raise OSError("UpdateProcThreadAttribute failed")

    return ctypes.cast(attr_list, ctypes.c_void_p)


def build_env_block(env: dict[str, str]) -> ctypes.Array[ctypes.c_wchar]:
    """Build null-terminated Unicode environment block."""
    env_str = "\x00".join(f"{k}={v}" for k, v in env.items()) + "\x00\x00"
    return ctypes.create_unicode_buffer(env_str)


def get_oem_encoding() -> str:
    """Detect Windows OEM code page for proper output decoding."""
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
        cp = kernel32.GetOEMCP()
        return f"cp{cp}"
    except (OSError, AttributeError):
        return "utf-8"


async def wrap_handles_as_process(
    process_handle: ctypes.wintypes.HANDLE,
    pid: int,
    stdin_write: ctypes.wintypes.HANDLE,
    stdout_read: ctypes.wintypes.HANDLE,
    kernel32: Any,
) -> asyncio.subprocess.Process:
    """Wrap Win32 handles into an asyncio-compatible subprocess.

    Uses msvcrt to convert Win32 HANDLEs to file descriptors, then wraps
    them as asyncio streams attached to a Process-like object.
    """
    import msvcrt

    stdin_fd = msvcrt.open_osfhandle(stdin_write, os.O_WRONLY)
    stdout_fd = msvcrt.open_osfhandle(stdout_read, os.O_RDONLY)

    stdin_file = os.fdopen(stdin_fd, "wb", buffering=0)
    stdout_file = os.fdopen(stdout_fd, "rb", buffering=0)

    loop = asyncio.get_running_loop()
    transport, protocol = await loop.connect_read_pipe(
        lambda: asyncio.StreamReaderProtocol(asyncio.StreamReader()),
        stdout_file,
    )
    stdout_reader = protocol._stream_reader  # type: ignore[attr-defined]

    w_transport, w_protocol = await loop.connect_write_pipe(
        asyncio.BaseProtocol, stdin_file
    )
    stdin_writer = asyncio.StreamWriter(w_transport, w_protocol, stdout_reader, loop)

    from myrm_agent_harness.toolkits.code_execution.sandbox.providers.appcontainer import (
        AppContainerProcess,
    )

    proc = AppContainerProcess(process_handle, pid, stdin_writer, stdout_reader, kernel32)
    return proc  # type: ignore[return-value]
