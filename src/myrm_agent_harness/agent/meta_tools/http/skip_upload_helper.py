"""Skip Upload Helper - Fast Upload Optimization

[INPUT]

[OUTPUT]
- bool (True if file already exists and MD5 matches, False otherwise)

[POS]
Instant upload optimization. Checks if a file already exists via HEAD request with MD5 matching to skip redundant uploads.

"""

from __future__ import annotations

import hashlib
import logging

from myrm_agent_harness.agent.meta_tools.http.client_pool import get_http_client

logger = logging.getLogger(__name__)


def calculate_md5(content: bytes) -> str:
    """Calculate MD5 hash of file content

    Args:
        content: File content bytes

    Returns:
        MD5 hash hex string
    """
    return hashlib.md5(content).hexdigest()


async def check_file_exists_by_md5(url: str, file_content: bytes, verify_ssl: bool = True) -> bool:
    """Check if file already exists on server with matching MD5

    Args:
        url: Target URL where file will be uploaded
        file_content: Local file content bytes
        verify_ssl: SSL verification

    Returns:
        True if file exists on server and MD5 matches (can skip upload),
        False otherwise (need to upload)

    Example:
        file_content = b"Hello, world!"
        can_skip = await check_file_exists_by_md5(
            url="https://upload.example.com/file.txt",
            file_content=file_content)
        if can_skip:
            logger.info("File already exists, skipping upload (fast upload optimization)")
        else:
            # Proceed with normal upload
            ...
    """
    try:
        # Calculate local file MD5
        local_md5 = calculate_md5(file_content)
        logger.debug(f"Local file MD5: {local_md5}")

        # HEAD request to check if file exists on server
        client = await get_http_client(verify_ssl)
        response = await client.head(url, follow_redirects=True)

        # Check if file exists (200 OK)
        if response.status_code != 200:
            logger.debug(f"File does not exist on server (status: {response.status_code})")
            return False

        # Check server MD5 (from Content-MD5 or ETag header)
        server_md5 = None
        if "Content-MD5" in response.headers:
            server_md5 = response.headers["Content-MD5"]
        elif "ETag" in response.headers:
            # ETag may be MD5 (strip quotes)
            etag = response.headers["ETag"].strip('"')
            if len(etag) == 32:  # MD5 is 32 hex chars
                server_md5 = etag

        if not server_md5:
            logger.debug("Server did not return MD5 (Content-MD5 or ETag header missing)")
            return False

        # Compare MD5
        if local_md5 == server_md5:
            logger.info(
                f"File already exists on server with matching MD5: {local_md5}, skipping upload (fast upload optimization)"
            )
            return True
        else:
            logger.debug(f"MD5 mismatch: local={local_md5}, server={server_md5}, need to upload")
            return False

    except Exception as e:
        logger.warning(f"Failed to check file existence: {e}, proceeding with upload")
        return False
