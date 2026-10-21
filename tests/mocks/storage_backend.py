"""In-memory storage backend for testing."""


class InMemoryStorageBackend:
    """In-memory implementation of StorageBackend for testing.

    This backend stores files in a dictionary, making it fast and
    suitable for unit tests without filesystem dependencies.

    Example:
        >>> backend = InMemoryStorageBackend()
        >>> await backend.write("test.txt", b"Hello")
        >>> content = await backend.read("test.txt")
        >>> assert content == b"Hello"
    """

    def __init__(self) -> None:
        """Initialize empty storage."""
        self._files: dict[str, bytes] = {}

    async def read(self, path: str) -> bytes:
        """Read file content from memory.

        Args:
            path: File path

        Returns:
            File content as bytes

        Raises:
            FileNotFoundError: If file does not exist
        """
        if path not in self._files:
            raise FileNotFoundError(f"File not found: {path}")
        return self._files[path]

    async def write(self, path: str, content: bytes) -> None:
        """Write file content to memory.

        Args:
            path: File path
            content: File content as bytes
        """
        self._files[path] = content

    async def exists(self, path: str) -> bool:
        """Check if file exists in memory.

        Args:
            path: File path

        Returns:
            True if file exists, False otherwise
        """
        return path in self._files

    async def list(self, prefix: str = "") -> list[str]:
        """List files with optional prefix filter.

        Args:
            prefix: Path prefix to filter (empty string = list all)

        Returns:
            List of file paths
        """
        if not prefix:
            return list(self._files.keys())
        return [path for path in self._files if path.startswith(prefix)]

    async def delete(self, path: str) -> None:
        """Delete a file from memory.

        Args:
            path: File path

        Raises:
            FileNotFoundError: If file does not exist
        """
        if path not in self._files:
            raise FileNotFoundError(f"File not found: {path}")
        del self._files[path]

    def clear(self) -> None:
        """Clear all files (useful for test cleanup)."""
        self._files.clear()

    def get_all_files(self) -> dict[str, bytes]:
        """Get all files (useful for assertions)."""
        return self._files.copy()
