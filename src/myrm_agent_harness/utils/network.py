"""Network utility functions.

[INPUT]

[OUTPUT]
- get_local_ip: str (local IP address)

[POS]
Pure network utilities. Get local IP using UDP socket (no actual data sent).
"""

from __future__ import annotations

import logging
import socket

logger = logging.getLogger(__name__)


def get_local_ip() -> str:
    """Get local LAN IP address.

    Uses UDP socket connection to external address to get local IP.
    This method does not actually send packets, it only uses OS routing table.

    Returns:
        Local IP address, falls back to "127.0.0.1" on failure

    Example:
        >>> ip = get_local_ip()
        >>> print(ip)  # e.g., "192.168.1.100"
    """
    try:
        # Create UDP socket
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            # Connect to external address (no data actually sent)
            s.connect(("8.8.8.8", 80))
            # Get socket's local address
            ip = s.getsockname()[0]
            logger.debug(f"Detected local IP: {ip}")
            return ip
    except OSError as e:
        logger.warning(f"Failed to detect local IP: {e}, falling back to 127.0.0.1")
        return "127.0.0.1"
    except Exception as e:
        logger.error(f"Unexpected error when detecting local IP: {e}")
        return "127.0.0.1"
