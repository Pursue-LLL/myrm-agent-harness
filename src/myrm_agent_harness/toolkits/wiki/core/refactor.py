"""Wiki link refactoring engine.

[INPUT]
pathlib::Path (POS: standard library file path operations)
re (POS: regular expressions)

[OUTPUT]
LinkRefactorEngine: Engine to update markdown links when files are moved/renamed.

[POS]
Handles the complexity of maintaining relative links in markdown files when
the directory structure changes (e.g., via drag-and-drop in the UI).
"""

import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)


class LinkRefactorEngine:
    """
    Engine to update markdown links when files are moved or renamed.
    """

    def __init__(self, concepts_dir: Path):
        self.concepts_dir = concepts_dir

    def refactor_links(self, old_path: Path, new_path: Path) -> int:
        """
        Scan all markdown files in concepts_dir and update links pointing to old_path.

        Args:
            old_path: The previous absolute path of the file/folder.
            new_path: The new absolute path of the file/folder.

        Returns:
            Number of files updated.
        """
        if not self.concepts_dir.exists():
            return 0

        updated_files_count = 0
        is_dir = old_path.is_dir() or new_path.is_dir()

        for md_file in self.concepts_dir.rglob("*.md"):
            # Skip the file that was just moved (its own internal relative links might need update too,
            # but for now we focus on incoming links from other files).
            # Actually, if a folder is moved, files inside it will have their outgoing relative links broken
            # if they point outside the folder. This is a complex case.
            # For MVP, we handle incoming links to the moved file/folder.

            try:
                content = md_file.read_text(encoding="utf-8")
                new_content = self._update_content_links(content, md_file, old_path, new_path, is_dir)

                if content != new_content:
                    md_file.write_text(new_content, encoding="utf-8")
                    updated_files_count += 1
            except Exception as e:
                logger.warning(f"Failed to refactor links in {md_file}: {e}")

        return updated_files_count

    def _update_content_links(
        self, content: str, current_file: Path, old_target: Path, new_target: Path, is_dir: bool
    ) -> str:
        """
        Update markdown links in the content.
        Matches [text](link) and updates the link if it resolves to old_target.
        """
        # Regex to find markdown links: [text](url)
        link_pattern = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")

        def replacer(match):
            text = match.group(1)
            url = match.group(2)

            # Ignore absolute URLs or anchors
            if url.startswith(("http://", "https://", "#", "mailto:")):
                return match.group(0)

            try:
                # Resolve the link relative to the current file's directory
                link_path = (current_file.parent / url).resolve()

                # Check if the link points to the old target or inside it (if it's a dir)
                needs_update = False
                if is_dir:
                    if old_target in link_path.parents or link_path == old_target:
                        needs_update = True
                else:
                    if link_path == old_target:
                        needs_update = True

                if needs_update:
                    # Calculate new absolute path
                    if is_dir:
                        rel_to_old = link_path.relative_to(old_target)
                        new_abs_path = new_target / rel_to_old
                    else:
                        new_abs_path = new_target

                    # Calculate new relative path from current file to new target
                    import os

                    new_rel_path = os.path.relpath(new_abs_path, current_file.parent)
                    # Ensure forward slashes for markdown links
                    new_rel_path = new_rel_path.replace("\\", "/")

                    return f"[{text}]({new_rel_path})"
            except Exception:
                pass

            return match.group(0)

        return link_pattern.sub(replacer, content)
