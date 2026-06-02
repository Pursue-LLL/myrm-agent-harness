"""Storage provider abstract base class.


[INPUT]
- abc::ABC, abstractmethod (POS: Python abstract base class)
- dataclasses::dataclass (POS: Python dataclass)
- datetime::datetime (POS: Python datetime type)

[OUTPUT]
- FileInfo: file metadata dataclass (key, size, last_modified, content_type)
- StorageProvider: storage provider abstract base class (defines unified storage interface)

[POS]
Storage provider abstract base class. Defines the unified storage interface contract for all
storage backends. Supports file read/write, delete, list, info query, and namespace isolation.
Method names use read/write (not get/put), fully compatible with the StorageBackend Protocol.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime


@dataclass
class FileInfo:
    """File info"""

    key: str  # File path/key
    size: int  # File size (bytes)
    last_modified: datetime  # Last modified time
    content_type: str | None = None  # MIME Type


class StorageProvider(ABC):
    """Storage provider abstract base class

    Defines a unified storage interface supporting:
    - File read/write (read/write)
    - File deletion
    - File listing
    - File info query
    - Namespace isolation (optional)

    Namespace:
         for 多租户隔离，Auto is AllPath添加Prefix。
        For example：namespace="sandboxes/user_alice_chat_123"
              read("file.txt") → 实际访问 "sandboxes/user_alice_chat_123/file.txt"

     using 统一  read/write Method名， no 需适配器i.e.可 for
    StorageSkillBackend  etc.框架层Component and 业务层工件收集。
    """

    def __init__(self, namespace: str | None = None):
        """InitializeStorageprovides者

        Args:
            namespace: Namespace（optional）， for Path隔离
                      如 "sandboxes/user_alice_chat_123"
        """
        self.namespace = namespace or ""

    def _get_full_key(self, key: str) -> str:
        """GetcompletePath（Auto添加 namespace Prefix）

        Args:
            key: 相对Path

        Returns:
            completePath（带 namespace Prefix）
        """
        if self.namespace:
            return f"{self.namespace}/{key}"
        return key

    def _strip_namespace(self, full_key: str) -> str:
        """移除 namespace Prefix

        Args:
            full_key: completePath

        Returns:
            相对Path（移除 namespace Prefix）
        """
        if self.namespace:
            prefix = f"{self.namespace}/"
            if full_key.startswith(prefix):
                return full_key[len(prefix) :]
        return full_key

    @abstractmethod
    async def read(self, key: str) -> bytes:
        """Read file content

        Args:
            key: File path/key

        Returns:
            FileContent（Bytes）

        Raises:
            FileNotFoundError: File not found
            StorageError: Storage操作Failure
        """
        ...

    @abstractmethod
    async def read_text(self, key: str, encoding: str = "utf-8") -> str:
        """读取textFileContent

        Args:
            key: File path/key
            encoding: textEncoding

        Returns:
            FileContent（String）

        Raises:
            FileNotFoundError: File not found
            StorageError: Storage操作Failure
        """
        ...

    @abstractmethod
    async def write(
        self, key: str, content: bytes, content_type: str | None = None
    ) -> None:
        """Write file

        Args:
            key: File path/key
            content: FileContent（Bytes）
            content_type: MIME Type

        Raises:
            StorageError: Storage操作Failure
        """
        ...

    @abstractmethod
    async def write_text(
        self,
        key: str,
        content: str,
        encoding: str = "utf-8",
        content_type: str | None = None,
    ) -> None:
        """写入textFile

        Args:
            key: File path/key
            content: FileContent（String）
            encoding: textEncoding
            content_type: MIME Type

        Raises:
            StorageError: Storage操作Failure
        """
        ...

    @abstractmethod
    async def delete(self, key: str) -> None:
        """Delete file

        Args:
            key: File path/key

        Raises:
            FileNotFoundError: File not found
            StorageError: Storage操作Failure
        """
        ...

    @abstractmethod
    async def exists(self, key: str) -> bool:
        """Check if file exists

        Args:
            key: File path/key

        Returns:
            Whether file exists
        """
        ...

    @abstractmethod
    async def is_dir(self, key: str) -> bool:
        """Check if path is a directory

        Args:
            key: File path/key

        Returns:
            Whether path is a directory
        """
        ...

    @abstractmethod
    async def list(self, prefix: str = "", recursive: bool = True) -> list[str]:
        """列出File

        Args:
            prefix: Path prefix
            recursive: Whetherrecursive列出子Directory

        Returns:
            FilePathList
        """
        ...

    @abstractmethod
    async def info(self, key: str) -> FileInfo:
        """GetFile info

        Args:
            key: File path/key

        Returns:
            File info

        Raises:
            FileNotFoundError: File not found
        """
        ...

    @abstractmethod
    async def copy(self, src_key: str, dst_key: str) -> None:
        """CopyFile

        Args:
            src_key: 源FilePath
            dst_key: 目标FilePath

        Raises:
            FileNotFoundError: 源File not found
            StorageError: Storage操作Failure
        """
        ...

    @abstractmethod
    async def move(self, src_key: str, dst_key: str) -> None:
        """MoveFile

        Args:
            src_key: 源FilePath
            dst_key: 目标FilePath

        Raises:
            FileNotFoundError: 源File not found
            StorageError: Storage操作Failure
        """
        ...

    @abstractmethod
    async def get_url(self, key: str, expires_in: int = 3600) -> str:
        """GetFile访问 URL

        Args:
            key: File path/key
            expires_in: URL Valid期（秒），Only对CloudStorageValid

        Returns:
            File访问 URL
            - LocalStorage：Return file:// URL
            - CloudStorage：ReturnSignature URL（带过期时间）

        Raises:
            FileNotFoundError: File not found
        """
        ...


class StorageError(Exception):
    """Storage操作Exception"""

    pass
