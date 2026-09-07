# mobile/

## Overview
Mobile Device ADB Wireless Bridge & Physical Device Automation Toolkit. Enables AI agents to interact with physical and virtual Android devices over USB and Android 11+ Wireless Debugging without physical cable constraints.

## File Index

| File | Role | Description |
|------|------|-------------|
| `__init__.py` | Package | Exports `create_mobile_tools`, `AdbDeviceManager`, `MobileInspector`, `MobileInputController`, `MobileAppManager` |
| `types.py` | Types | Data models: `MobileDeviceInfo`, `MobileElementNode`, `MobileActionResult`, `DeviceConnectionState`, `MobileKeyEvent` |
| `protocols.py` | Interfaces | Core backend protocols: `MobileDeviceBackendProtocol`, `MobileInspectorProtocol`, `MobileInputProtocol`, `MobileAppManagerProtocol` |
| `device_manager.py` | Driver | Wireless pairing (`adb pair`), dynamic port connection, auto-enrichment, and async shell execution |
| `inspector.py` | Perception | Fast screen capture (`screencap -p`) and Accessibility UI hierarchy parsing with normalized coordinate calculation |
| `input_controller.py` | Interaction | Tap, swipe, hardware keyevents, and Unicode / Chinese Base64 IME text injection |
| `app_manager.py` | Lifecycle | App launch by package/alias, force stop, and installed package enumeration |
| `mobile_agent_tools.py` | Surface | 3 LangChain Agent tools: `mobile_device_connect`, `mobile_snapshot`, `mobile_interact` |

## Architecture

```
Agent → mobile_agent_tools (3 tools)
          ├─ mobile_device_connect → AdbDeviceManager (pairing & TCP connect)
          ├─ mobile_snapshot       → MobileInspector (screencap & UI tree)
          └─ mobile_interact       → MobileInputController (touch, gestures, IME)
                                   → MobileAppManager (monkey / am start)
                                        └─ ADB Daemon / Android OS
```
