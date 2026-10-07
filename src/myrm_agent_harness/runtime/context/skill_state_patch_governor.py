from __future__ import annotations

import copy
import json
import re

from myrm_agent_harness.runtime.context.skill_state_types import (
    PrebuiltStateSchemaKind,
    clone_state,
)


def apply_rfc7386_merge_patch(
    target: dict[str, object],
    patch: dict[str, object],
) -> dict[str, object]:
    """Pure RFC 7386 JSON Merge Patch implementation.

    - If patch value is None: remove the key if it exists in target.
    - If patch value is a dict and target value is a dict: merge recursively.
    - Otherwise: replace target value with a copy of patch value.
    Returns a newly constructed patched dict without mutating the original input.
    """
    result = clone_state(target)
    for key, val in patch.items():
        if val is None:
            result.pop(key, None)
        elif isinstance(val, dict) and isinstance(result.get(key), dict):
            target_sub = result[key]
            assert isinstance(target_sub, dict)
            result[key] = apply_rfc7386_merge_patch(target_sub, val)
        else:
            result[key] = copy.deepcopy(val)
    return result


class JsonMergePatchGovernor:
    """Governor and validation gate for deterministic state patches."""

    def __init__(self, allowed_schema: PrebuiltStateSchemaKind | None = None) -> None:
        self._allowed_schema = allowed_schema

    def sanitize_patch_input(self, patch_raw: str | dict[str, object]) -> dict[str, object]:
        """Extract and sanitize patch dict from json string, fences, or wrappers."""
        if isinstance(patch_raw, dict):
            patch_dict = copy.deepcopy(patch_raw)
        else:
            clean_str = patch_raw.strip()
            # Strip markdown codeblocks if present
            fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", clean_str)
            if fence_match:
                clean_str = fence_match.group(1).strip()
            parsed = json.loads(clean_str)
            if not isinstance(parsed, dict):
                raise ValueError(f"State patch must be a JSON object, got {type(parsed).__name__}")
            patch_dict = parsed

        # Unpack commonly emitted wrapper keys by smaller models (e.g., {"$set": {...}})
        if "$set" in patch_dict and isinstance(patch_dict["$set"], dict) and len(patch_dict) == 1:
            patch_dict = patch_dict["$set"]
        elif "patch" in patch_dict and isinstance(patch_dict["patch"], dict) and len(patch_dict) == 1:
            patch_dict = patch_dict["patch"]

        return patch_dict

    def validate_patch(
        self,
        current_state: dict[str, object],
        patch: dict[str, object],
        schema_kind: PrebuiltStateSchemaKind | None = None,
    ) -> tuple[bool, str | None]:
        """Validate patch compliance against schema integrity rules."""
        active_schema = schema_kind or self._allowed_schema
        if active_schema is None:
            return True, None

        if active_schema == PrebuiltStateSchemaKind.SOFTWARE_REPOSITORY:
            if "ci_matrix_status" in patch and not isinstance(patch["ci_matrix_status"], (dict, type(None))):
                return False, "ci_matrix_status must be a dictionary or None"
            if "modified_files" in patch and not isinstance(patch["modified_files"], (list, type(None))):
                return False, "modified_files must be a list or None"

        elif active_schema == PrebuiltStateSchemaKind.REVERSE_ENGINEERING:
            if "discovered_flags" in patch and not isinstance(patch["discovered_flags"], (list, type(None))):
                return False, "discovered_flags must be a list or None"

        elif active_schema == PrebuiltStateSchemaKind.RESOURCE_INVENTORY:
            if "quota_limits" in patch and not isinstance(patch["quota_limits"], (dict, type(None))):
                return False, "quota_limits must be a dictionary or None"

        elif active_schema == PrebuiltStateSchemaKind.BUSINESS_TRANSACTION:
            if "cart_items" in patch and not isinstance(patch["cart_items"], (list, type(None))):
                return False, "cart_items must be a list or None"

        elif active_schema == PrebuiltStateSchemaKind.CODING_BUGFIX_LOOP:
            if "reproducing_test_passed" in patch and not isinstance(patch["reproducing_test_passed"], (bool, type(None))):
                return False, "reproducing_test_passed must be a boolean or None"

        return True, None

    def safe_atomic_apply(
        self,
        current_state: dict[str, object],
        patch_raw: str | dict[str, object],
        schema_kind: PrebuiltStateSchemaKind | None = None,
    ) -> tuple[dict[str, object], bool, str | None]:
        """Atomically validate and merge patch without mutating state on failure."""
        try:
            sanitized_patch = self.sanitize_patch_input(patch_raw)
        except Exception as exc:
            return current_state, False, f"Malformed patch payload: {exc}"

        valid, err = self.validate_patch(current_state, sanitized_patch, schema_kind)
        if not valid:
            return current_state, False, err

        try:
            merged = apply_rfc7386_merge_patch(current_state, sanitized_patch)
            return merged, True, None
        except Exception as exc:
            return current_state, False, f"Merge execution error: {exc}"
