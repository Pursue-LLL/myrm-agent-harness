"""Android ADB Wireless Debugging Backend & Primitives.

[INPUT]
- computer_use/types::ActionResult, ScreenInfo (POS: shared computer_use contracts)

[OUTPUT]
- AndroidAdbBackend: Asynchronous wireless ADB backend driver with WebP compression & XML pruning.
- AndroidAdbClient: Direct ADB TCP client for wireless pairing, probes, and shell execution.
- MobileNode: Parsed accessibility node extracted from Android UIAutomator XML tree.

[POS]
Backend extension for Android mobile device automation over Wireless ADB.
"""

from __future__ import annotations

from .client import AndroidAdbClient
from .compressor import compress_screencap_bytes
from .tree_pruner import AndroidUiPruner, MobileNode
from .driver import AndroidAdbBackend

__all__ = [
    "AndroidAdbClient",
    "AndroidAdbBackend",
    "AndroidUiPruner",
    "MobileNode",
    "compress_screencap_bytes",
]
