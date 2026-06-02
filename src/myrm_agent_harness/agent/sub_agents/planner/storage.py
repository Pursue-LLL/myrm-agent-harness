"""Planner Storage Adapter

Adapts StorageBackend for planner-specific storage operations.
Implements shadow sync (3 files: plan.json, task_plan.md, plan_summary.txt).

[INPUT]
- toolkits.storage.base::StorageProvider (POS: Storage provider abstract base class. Defines the unified storage interface contract for all storage backends. Supports file read/write, delete, list, info query, and namespace isolation. Method names use read/write (not get/put), fully compatible with the StorageBackend Protocol.)
- toolkits.storage::StorageProvider (POS: Planner Storage Adapter)

[OUTPUT]
- PlannerStorage: Planner storage adapter

[POS]
Planner Storage Adapter
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from myrm_agent_harness.agent.sub_agents.planner.schemas import Plan
    from myrm_agent_harness.toolkits.storage.base import StorageProvider

logger = logging.getLogger(__name__)


class PlannerStorage:
    """Planner storage adapter

    Wraps StorageBackend to provide planner-specific storage operations.
    Implements shadow sync pattern: saves plan in multiple formats for different use cases.

    Files generated:
    1. plan.json - Structured data (agent access, complete info)
    2. task_plan.md - User-friendly view (includes progress, findings, errors)
    3. plan_summary.txt - Ultra-short summary (middleware quick injection)

    Args:
        storage_backend: Storage backend implementation
        prefix: Storage path prefix (default: "/planner")

    Example:
        >>> from myrm_agent_harness.toolkits.storage import StorageProvider
        >>> storage = StorageBackend.local("./workspace")
        >>> planner_storage = PlannerStorage(storage, prefix="/planner")
        >>> await planner_storage.save_plan(plan)
    """

    def __init__(self, storage_backend: StorageProvider, prefix: str = "/planner"):
        """Initialize planner storage

        Args:
            storage_backend: Storage backend implementation
            prefix: Storage path prefix
        """
        self.storage = storage_backend
        self.prefix = prefix.rstrip("/")

    def _get_path(self, filename: str) -> str:
        """Get full file path

        Args:
            filename: File name

        Returns:
            Full path with prefix
        """
        return f"{self.prefix}/{filename}"

    def _strip_line_numbers(self, content: str) -> str:
        """Strip line numbers from content if present

        Some storage backends (like LocalStorage) add line numbers for AI readability,
        but this breaks JSON/structured data parsing. This method removes them.

        Args:
            content: Content that may have line numbers (format: " 1|line content")

        Returns:
            Content without line numbers
        """
        # Check if content has line numbers (format: " 1|...")
        if re.match(r"^\s*\d+\|", content):
            # Remove line numbers from each line
            lines = content.splitlines()
            stripped_lines = [re.sub(r"^\s*\d+\|", "", line) for line in lines]
            return "\n".join(stripped_lines)

        return content

    async def save_plan(self, plan: Plan) -> None:
        """Save plan (shadow sync)

        Saves plan in 3 formats:
        1. plan.json - Complete structured data
        2. task_plan.md - User-friendly markdown view
        3. plan_summary.txt - Ultra-short summary

        Args:
            plan: Plan object to save

        Raises:
            Exception: If any write operation fails
        """
        # Prepare file contents
        json_content = plan.model_dump_json(indent=2)
        markdown_content = plan.to_markdown()
        summary_content = plan.to_summary()

        # Write files sequentially
        files = [
            ("plan.json", json_content),
            ("task_plan.md", markdown_content),
            ("plan_summary.txt", summary_content),
        ]

        errors = []
        for filename, content in files:
            try:
                await self._write_file(filename, content)
            except Exception as e:
                errors.append((filename, e))

        # Check for errors
        if errors:
            error_msg = f"Shadow sync had {len(errors)} error(s): {errors[0][1]}"
            logger.warning(" %s", error_msg)
            raise RuntimeError(error_msg)

        logger.warning(" Shadow sync complete: plan.json + task_plan.md + plan_summary.txt")

    async def _write_file(self, filename: str, content: str) -> None:
        """Write file helper

        Args:
            filename: File name
            content: File content
        """
        path = self._get_path(filename)
        try:
            await self.storage.write_text(path, content)
        except Exception as e:
            msg = f"Failed to write {path}: {e}"
            raise RuntimeError(msg) from e

    async def load_plan(self) -> Plan | None:
        """Load plan from storage

        Returns:
            Plan object if exists, None otherwise

        Raises:
            Exception: If plan.json exists but parsing fails
        """
        from myrm_agent_harness.agent.sub_agents.planner.schemas import Plan

        path = self._get_path("plan.json")
        try:
            content = await self.storage.read_text(path)
        except FileNotFoundError:
            return None

        try:
            # Remove line numbers if present (format: " 1|content")
            content = self._strip_line_numbers(content)
            return Plan.model_validate_json(content)
        except Exception as e:
            msg = f"Failed to parse plan.json: {e}"
            logger.warning(" %s", msg)
            raise RuntimeError(msg) from e

    async def plan_exists(self) -> bool:
        """Check if plan exists

        Returns:
            True if plan.json exists
        """
        path = self._get_path("plan.json")
        return await self.storage.exists(path)

    async def delete_plan(self) -> bool:
        """Delete all plan files

        Deletes plan.json, task_plan.md, and plan_summary.txt.

        Returns:
            True if at least one file was deleted
        """
        files = ["plan.json", "task_plan.md", "plan_summary.txt"]
        deleted = False

        for filename in files:
            path = self._get_path(filename)
            if await self.storage.exists(path):
                await self.storage.delete(path)
                deleted = True
                logger.warning(" Deleted %s", path)

        return deleted

    async def get_summary(self) -> str | None:
        """Get plan summary

        Returns:
            Plan summary text if exists, None otherwise
        """
        path = self._get_path("plan_summary.txt")
        try:
            content = await self.storage.read_text(path)
            return self._strip_line_numbers(content)
        except FileNotFoundError:
            return None

    async def get_markdown(self) -> str | None:
        """Get plan markdown

        Returns:
            Plan markdown text if exists, None otherwise
        """
        path = self._get_path("task_plan.md")
        try:
            content = await self.storage.read_text(path)
            return self._strip_line_numbers(content)
        except FileNotFoundError:
            return None
