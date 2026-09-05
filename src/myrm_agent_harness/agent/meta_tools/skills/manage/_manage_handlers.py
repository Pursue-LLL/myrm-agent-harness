"""Skill management action handlers and validation helpers.

[INPUT]
- backends.skills.scanning::ScanningSkillWriteBackend (POS: Framework-level security wrapper for SkillWriteBackend)
- backends.skills.protocols::SkillBackend (POS: Skill backend protocol definition)
- backends.skills.similarity::SkillSimilarityChecker (POS: Skill similarity checking protocol)
- agent.context_management.context::extract_context_from_runnable_config (POS: Context extraction helper)
- utils.fuzzy_match::fuzzy_replace (POS: Progressive fuzzy replace utility)

[OUTPUT]
- _extract_user_id: Extract user_id from RunnableConfig context
- _validate_name: Skill name validation
- _validate_frontmatter: YAML frontmatter format validation
- _handle_save: Create or fully replace a skill
- _handle_patch: Partial content replacement
- _handle_delete: Remove a skill
- _handle_write_file: Add or overwrite a supporting file
- _handle_remove_file: Delete a supporting file
- _handle_evolution_lock: Toggle evolution lock on a skill

[POS]
Internal handlers and validation logic for skill_manage_tool actions (save, patch, delete, write_file, remove_file, lock, unlock).
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from langchain_core.runnables import RunnableConfig

from myrm_agent_harness.agent.context_management.context import (
    extract_context_from_runnable_config,
)

if TYPE_CHECKING:
    from myrm_agent_harness.backends.skills.protocols import SkillBackend
    from myrm_agent_harness.backends.skills.scanning import (
        ScanningSkillWriteBackend,
    )
    from myrm_agent_harness.backends.skills.similarity import SkillSimilarityChecker

logger = logging.getLogger(__name__)

SKILL_NAME_PATTERN = re.compile(r"^[a-zA-Z][a-zA-Z0-9_-]*$")

__all__ = [
    "SKILL_NAME_PATTERN",
    "_apply_patch",
    "_check_similarity",
    "_extract_user_id",
    "_handle_delete",
    "_handle_evolution_lock",
    "_handle_patch",
    "_handle_remove_file",
    "_handle_save",
    "_handle_write_file",
    "_validate_frontmatter",
    "_validate_name",
]


def _extract_user_id(config: RunnableConfig) -> str:
    """Extract user_id from RunnableConfig context (framework pattern)."""
    context = extract_context_from_runnable_config(config)
    uid = str(context.get("user_id", ""))
    if not uid:
        raise ValueError(
            "user_id is required in RunnableConfig context for skill operations. "
            "Business layer must set context['user_id']."
        )
    return uid


# ---------------------------------------------------------------------------
# Action handlers
# ---------------------------------------------------------------------------


async def _handle_save(
    write_backend: ScanningSkillWriteBackend,
    name: str,
    content: str,
    description: str,
    user_id: str,
    similarity_checker: SkillSimilarityChecker | None = None,
) -> str:
    """Handle the 'save' action: create or fully replace a skill."""
    if not content or not content.strip():
        return "Error: 'content' is required for save action. Provide complete SKILL.md with YAML frontmatter."

    frontmatter_error = _validate_frontmatter(content)
    if frontmatter_error:
        return frontmatter_error

    result = await write_backend.save_skill(name=name, content=content, user_id=user_id, description=description)

    if result.success:
        action_word = "updated" if result.was_updated else "created"
        msg = (
            f"Skill '{result.skill_name}' {action_word} successfully!\n"
            f"  ID: {result.skill_id}\n"
            f"  Path: {result.saved_path}\n\n"
            f"The skill will be available in the user's next conversation."
        )
        if not result.was_updated:
            similarity_warning = await _check_similarity(similarity_checker, name, description)
            if similarity_warning:
                msg += f"\n\n--- Similarity Warning ---\n{similarity_warning}"
        if result.scan_report and "finding(s)" in result.scan_report:
            msg += f"\n\n--- Security Scan ---\n{result.scan_report}"
        return msg

    return f"Error: {result.error}"


async def _check_similarity(
    checker: SkillSimilarityChecker | None,
    name: str,
    description: str,
) -> str:
    """Check for semantically similar existing skills. Returns warning text or empty string."""
    if checker is None:
        return ""
    try:
        similar = await checker.find_similar(name, description, top_k=3, threshold=0.6)
        if not similar:
            return ""
        lines = ["Similar skill(s) already exist. Consider using 'patch' to update instead of creating a duplicate:"]
        for s in similar:
            lines.append(f"  - '{s.name}' ({s.similarity_score:.0%} similar): {s.description}")
        return "\n".join(lines)
    except Exception as e:
        logger.warning("Similarity check failed (non-blocking): %s", e)
        return ""


async def _handle_patch(
    write_backend: ScanningSkillWriteBackend,
    skill_backend: SkillBackend | None,
    name: str,
    old_content: str,
    new_content: str,
    user_id: str,
) -> str:
    """Handle the 'patch' action: partial content replacement."""
    if not old_content:
        return "Error: 'old_content' is required for patch action. Provide the exact fragment to replace."
    if not new_content:
        return "Error: 'new_content' is required for patch action. Provide the replacement fragment."

    if skill_backend is None:
        return "Error: Cannot patch — skill backend is not configured."

    try:
        current_content = await skill_backend.get_skill_content(name)
    except FileNotFoundError:
        return f"Error: Skill '{name}' not found. Use 'save' action to create it first."
    except Exception as e:
        logger.error("Failed to read skill '%s': %s", name, e)
        return f"Error: Failed to read skill '{name}': {e}"

    patched = _apply_patch(current_content, old_content, new_content)
    if patched is None:
        return (
            f"Error: Could not find the specified fragment in skill '{name}'.\n"
            f"The old_content must match exactly (or after trimming leading/trailing whitespace per line).\n"
            f"Use 'save' action with full content for a complete replacement."
        )

    result = await write_backend.save_skill(name=name, content=patched, user_id=user_id)

    if result.success:
        msg = f"Skill '{name}' patched successfully!"
        if result.scan_report and "finding(s)" in result.scan_report:
            msg += f"\n\n--- Security Scan ---\n{result.scan_report}"
        return msg

    return f"Error: {result.error}"


async def _handle_delete(write_backend: ScanningSkillWriteBackend, name: str, user_id: str) -> str:
    """Handle the 'delete' action: remove a skill."""
    result = await write_backend.delete_skill(name=name, user_id=user_id)

    if result.success:
        return f"Skill '{name}' deleted successfully."

    return f"Error: {result.error}"


async def _handle_write_file(
    write_backend: ScanningSkillWriteBackend,
    name: str,
    file_path: str,
    content: str,
    user_id: str,
) -> str:
    """Handle the 'write_file' action: add/overwrite a supporting file."""
    if not file_path or not file_path.strip():
        return (
            "Error: 'file_path' is required for write_file action.\n"
            "Example: 'scripts/analyze.py' or 'references/api_docs.md'."
        )
    if not content:
        return "Error: 'content' is required for write_file action."

    result = await write_backend.write_resource(
        skill_name=name, resource_path=file_path, content=content, user_id=user_id
    )

    if result.success:
        msg = f"File '{file_path}' written to skill '{name}' successfully."
        if result.scan_report and "finding(s)" in result.scan_report:
            msg += f"\n\n--- Security Scan ---\n{result.scan_report}"
        return msg

    return f"Error: {result.error}"


async def _handle_remove_file(write_backend: ScanningSkillWriteBackend, name: str, file_path: str, user_id: str) -> str:
    """Handle the 'remove_file' action: delete a supporting file."""
    if not file_path or not file_path.strip():
        return (
            "Error: 'file_path' is required for remove_file action.\n"
            "Example: 'scripts/analyze.py' or 'references/api_docs.md'."
        )

    result = await write_backend.delete_resource(skill_name=name, resource_path=file_path, user_id=user_id)

    if result.success:
        return f"File '{file_path}' removed from skill '{name}' successfully."

    return f"Error: {result.error}"


async def _handle_evolution_lock(name: str, *, locked: bool) -> str:
    """Handle the 'lock'/'unlock' action: toggle evolution lock on a skill.

    Uses the global evolution integration's SkillStore to set/unset the lock.
    Locked skills are protected from auto-evolution (FIX/DERIVED), preserving
    user-edited content.
    """
    try:
        from myrm_agent_harness.agent.skills.evolution.infra.integration import (
            get_global_evolution_integration,
        )

        evolution = get_global_evolution_integration()
        if not evolution or not evolution.store:
            return "Error: Evolution system not initialized. Cannot lock/unlock skills."

        store = evolution.store
        skill = store.get_skill(name)
        if not skill:
            return f"Error: Skill '{name}' not found in evolution store."

        await store.set_evolution_lock(skill.skill_id, locked=locked)
        action_word = "locked" if locked else "unlocked"
        return (
            f"Skill '{name}' {action_word} successfully. "
            f"{'Auto-evolution is now disabled for this skill.' if locked else 'Auto-evolution is now re-enabled.'}"
        )
    except Exception as e:
        logger.error("Failed to %s skill '%s': %s", "lock" if locked else "unlock", name, e)
        action_word = "lock" if locked else "unlock"
        return f"Error: Failed to {action_word} skill '{name}': {e}"


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _validate_name(name: str) -> str | None:
    """Validate skill name, returning error message or None."""
    if not name or not name.strip():
        return "Error: Skill name cannot be empty.\nFix: Provide a name like 'code_review_skill'."

    if len(name) > 64:
        return f"Error: Skill name too long ({len(name)} chars, max 64).\nFix: Shorten to 64 characters or less."

    if not SKILL_NAME_PATTERN.match(name):
        suggested = re.sub(r"[^a-zA-Z0-9_-]+", "_", name.strip())
        suggested = re.sub(r"^[^a-zA-Z]+", "", suggested).rstrip("_-").lower()
        return (
            f"Error: Invalid skill name '{name}'.\n"
            f"Rules: Must start with a letter, contain only letters/numbers/underscores/hyphens.\n"
            f"Suggested fix: '{suggested or 'my_skill'}'"
        )

    return None


def _validate_frontmatter(content: str) -> str | None:
    """Validate YAML frontmatter format."""
    stripped = content.strip()
    if not stripped.startswith("---"):
        return (
            "Error: SKILL.md must start with YAML frontmatter (---).\n"
            "Fix: Add frontmatter at the beginning:\n"
            "---\n"
            "name: your_skill_name\n"
            'description: "Brief description"\n'
            "---"
        )

    end_idx = stripped.find("---", 3)
    if end_idx == -1:
        return (
            "Error: YAML frontmatter is not closed (missing closing ---).\nFix: Add '---' after the frontmatter fields."
        )

    frontmatter_block = stripped[3:end_idx].strip()
    if not frontmatter_block:
        return (
            "Error: YAML frontmatter is empty.\n"
            "Fix: Add at least 'name' and 'description' fields:\n"
            "---\n"
            "name: your_skill_name\n"
            'description: "Brief description"\n'
            "---"
        )

    lines = frontmatter_block.split("\n")
    has_name = any(line.strip().startswith("name:") for line in lines)
    has_description = any(line.strip().startswith("description:") for line in lines)

    missing: list[str] = []
    if not has_name:
        missing.append("name")
    if not has_description:
        missing.append("description")

    if missing:
        return (
            f"Error: YAML frontmatter missing required field(s): {', '.join(missing)}.\n"
            f"Fix: Add the missing field(s) to the frontmatter:\n"
            f"---\n"
            f"name: your_skill_name\n"
            f'description: "Brief description"\n'
            f"---"
        )

    return None


# ---------------------------------------------------------------------------
# Patch logic — delegates to utils.fuzzy_match (7-level progressive strategy)
# ---------------------------------------------------------------------------


def _apply_patch(full_content: str, old_fragment: str, new_fragment: str) -> str | None:
    """Apply a patch to content with progressive fuzzy matching fallback.

    Uses the shared fuzzy_replace utility (7-level strategy chain).
    Returns patched content, or None if no match found.
    """
    from myrm_agent_harness.utils.fuzzy_match import fuzzy_replace

    result = fuzzy_replace(full_content, old_fragment, new_fragment)
    return result.content if result.success else None
