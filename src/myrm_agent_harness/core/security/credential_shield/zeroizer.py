"""Ephemeral credential zeroizer and secure memory wiper.

[INPUT]
- Sensitive credential strings or byte buffers.

[OUTPUT]
- Piped streams with in-memory zeroization ensuring no leftover credentials in memory dumps.

[POS]
- Harness core security memory safety helper.
"""

from __future__ import annotations

import io
from typing import BinaryIO


class EphemeralCredentialZeroizer:
    """Safely handles in-memory credentials, wiping byte buffers with zeroes immediately after use."""

    @staticmethod
    def wipe_buffer(buffer: bytearray) -> None:
        """Overwrite a mutable bytearray with null bytes in-place."""
        for i in range(len(buffer)):
            buffer[i] = 0

    @classmethod
    def pipe_and_wipe(
        cls,
        credential_data: str | bytes,
        destination_stream: BinaryIO | io.BytesIO,
    ) -> int:
        """Write credential data to stream and zeroize the working memory buffer immediately."""
        raw_bytes = (
            credential_data.encode("utf-8")
            if isinstance(credential_data, str)
            else credential_data
        )
        mutable_buf = bytearray(raw_bytes)
        try:
            bytes_written = destination_stream.write(mutable_buf)
            if hasattr(destination_stream, "flush"):
                destination_stream.flush()
            return bytes_written
        finally:
            cls.wipe_buffer(mutable_buf)
