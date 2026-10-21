# providers/

## Overview
Built-in sandbox providers. Each platform has a dedicated provider:

| Platform | Provider | Mechanism |
|----------|----------|-----------|
| Linux | BwrapProvider | bubblewrap namespace isolation |
| macOS | SeatbeltProvider | sandbox-exec SBPL profile |
| Windows | AppContainerProvider | AppContainer security token |
| Fallback | NullProvider | transparent passthrough (no isolation) |

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Built-in sandbox providers. | — |
| _win32_defs.py | Internal | Win32 ctypes structures and low-level API helpers. | ✅ |
| appcontainer.py | Core | Windows AppContainer native process sandbox. | ✅ |
| bwrap.py | Core | Linux bubblewrap (bwrap) sandbox provider. | ✅ |
| null.py | Core | No-op sandbox provider — transparent passthrough. | ✅ |
| seatbelt.py | Core | macOS sandbox-exec (Seatbelt) sandbox provider. | ✅ |
