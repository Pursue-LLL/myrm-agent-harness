"""Skill backend utilities — frontmatter parsing.

1. 本文件的 INPUT/OUTPUT/POS 注释

[INPUT]
- yaml::yaml (POS: YAML 解析库)
- re::re (POS: 正则表达式库)
- types::SkillRequires (POS: 技能依赖声明类型)

[OUTPUT]
- SkillMetadataError: 技能元数据解析或验证错误异常
- SkillFrontmatter: 解析后的 frontmatter 数据
- parse_skill_frontmatter(): 从 SKILL.md 解析完整 frontmatter（返回 SkillFrontmatter）

[POS]
Skill backend parsing utilities. Provides SKILL.md frontmatter parsing functionality.

"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from myrm_agent_harness.backends.skills.types import (
    SkillContract,
    SkillContractJudgment,
    SkillContractTrap,
    SkillContractVerification,
    SkillRequires,
)

logger = logging.getLogger(__name__)

# agentskills.io specification constraints
_MAX_DESCRIPTION_LENGTH = 1024
_MAX_COMPATIBILITY_LENGTH = 500
_MAX_NAME_LENGTH = 64
_MAX_SKILL_FILE_SIZE = 1 * 1024 * 1024  # 1 MB max for SKILL.md


class SkillMetadataError(Exception):
    """Skill metadata parsing or validation error."""

    pass


@dataclass
class SkillFrontmatter:
    """Parsed SKILL.md frontmatter data (agentskills.io spec compliant).

    Contains all fields from the agentskills.io specification plus
    our extensions (activation criteria, dependency requirements, hooks,
    allowed-tools with hook-level control).
    """

    description: str
    """Skill description (truncated to 1024 chars per spec)"""

    name: str | None = None
    """Skill name from frontmatter (may differ from directory name)"""

    license: str | None = None
    """License name or reference"""

    compatibility: str | None = None
    """Environment requirements (truncated to 500 chars per spec)"""

    metadata: dict[str, str] = field(default_factory=dict)
    """Arbitrary key-value metadata (e.g. author, version)"""

    allowed_tools: str | None = None
    """Space-delimited pre-approved tools (experimental per spec)"""

    requires: SkillRequires | None = None
    """External dependency requirements (bins/env/config)"""

    requires_tools: list[str] = field(default_factory=list)
    """Skill hidden when any listed tool is absent from the agent's tool set."""

    fallback_for_tools: list[str] = field(default_factory=list)
    """Skill hidden when any listed tool IS present (fallback for that tool)."""

    requires_tool_groups: list[str] = field(default_factory=list)
    """Skill hidden when any listed tool group is not enabled on the agent."""

    fallback_for_tool_groups: list[str] = field(default_factory=list)
    """Skill hidden when any listed tool group IS enabled (fallback for that group)."""

    always: bool = False
    """If True, always included in skill_select_tool XML (get_metadata_summary), not SystemMessage."""

    model_invocable: bool = True
    """Whether the model can auto-select this skill via skill_select_tool"""

    user_invocable: bool = True
    """Whether the user can manually trigger this skill (e.g. via / command or UI)"""

    version: str | None = None
    """Skill version string for version management"""

    category: str | None = None
    """Skill category for UI grouping"""

    primary_env: str | None = None
    """Primary environment variable name for apiKey auto-mapping (e.g. "BRAVE_API_KEY").
    When set, users can configure a single apiKey that auto-maps to this env var."""

    allowed_domains: list[str] | None = None
    """Allowed domains for outbound network requests (DLP protection)."""

    required_credential_files: list[str] = field(default_factory=list)
    """Required credential files for this skill (relative to workspace root)."""

    credential_env_mapping: dict[str, str] = field(default_factory=dict)
    """Environment variable mappings for credential files."""

    evolution_locked: bool = False
    """If True, this skill is locked from automatic evolution."""

    config_schema: dict[str, object] | None = None
    """JSON Schema for skill configuration. When provided, enables type-safe
    configuration UI and validation for SkillInstanceConfig.config_overrides.
    Uses a subset of JSON Schema (properties, type, enum, default, required,
    minimum, maximum, format). Example in SKILL.md frontmatter:
        config-schema:
          type: object
          properties:
            api_key: {type: string, format: password, title: API Key}
            timeout: {type: integer, default: 30, minimum: 1, maximum: 300}
    """

    contract: SkillContract | None = None
    """Structured contract used for cache-safe routing and degraded fallback."""

    scope_agent_id: str | None = None
    """Agent ID that owns this skill (for Multi-Agent scoping)."""


def _parse_frontmatter_yaml(content: str, skill_dir_name: str) -> dict[str, object]:
    """Extract and parse YAML frontmatter from SKILL.md content.

    Args:
        content: Full SKILL.md file content
        skill_dir_name: Directory name (for error messages)

    Returns:
        Parsed YAML dict

    Raises:
        SkillMetadataError: If frontmatter is missing or invalid
    """
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n", content, re.DOTALL)
    if not match:
        raise SkillMetadataError(
            f"No YAML frontmatter found in SKILL.md.\n"
            f"Expected format (first 3 lines must be):\n"
            f"---\n"
            f"description: Brief description of {skill_dir_name}\n"
            f"---"
        )

    frontmatter_text = match.group(1)

    try:
        parsed = yaml.safe_load(frontmatter_text)
    except yaml.YAMLError as e:
        raise SkillMetadataError(f"Invalid YAML syntax in frontmatter: {e}") from e

    if not isinstance(parsed, dict):
        raise SkillMetadataError(f"Frontmatter must be a YAML object, got: {type(parsed).__name__}")

    return parsed


_KNOWN_FRONTMATTER_FIELDS = frozenset(
    {
        "name",
        "description",
        "version",
        "license",
        "compatibility",
        "metadata",
        "allowed-tools",
        "allowed-domains",
        "requires",
        "always",
        "model-invocable",
        "user-invocable",
        "disable-model-invocation",
        "hooks",
        "category",
        "author",
        "homepage",
        "tags",
        "primaryEnv",
        "primary_env",
        "required-credential-files",
        "required_credential_files",
        "credential-env-mapping",
        "credential_env_mapping",
        "evolution-locked",
        "evolution_locked",
        "config-schema",
        "config_schema",
        "contract",
        "requires-tools",
        "requires_tools",
        "fallback-for-tools",
        "fallback_for_tools",
        "requires-tool-groups",
        "requires_tool_groups",
        "fallback-for-tool-groups",
        "fallback_for_tool_groups",
        "scope_agent_id",
    }
)


def _validate_and_extract_description(parsed: dict[str, object], skill_dir_name: str) -> str:
    """Validate and extract description field per agentskills.io spec.

    Truncates to 1024 characters if exceeded. Strips XML angle brackets
    to prevent injection into XML summaries.

    Args:
        parsed: Parsed YAML frontmatter dict
        skill_dir_name: Directory name (for error messages)

    Returns:
        Validated description string (max 1024 chars, XML-safe)
    """
    if "description" not in parsed:
        raise SkillMetadataError(
            f"Required field 'description' missing in frontmatter.\n"
            f"Add this line to your frontmatter:\n"
            f"description: Brief description of {skill_dir_name}"
        )

    description = str(parsed["description"]).strip()
    if not description:
        raise SkillMetadataError(
            f"Field 'description' cannot be empty.\nProvide a meaningful description for {skill_dir_name}"
        )

    if len(description) > _MAX_DESCRIPTION_LENGTH:
        logger.warning(
            f"Skill '{skill_dir_name}' description truncated from {len(description)} to {_MAX_DESCRIPTION_LENGTH} chars"
        )
        description = description[:_MAX_DESCRIPTION_LENGTH]

    if "<" in description or ">" in description:
        logger.warning(f"Skill '{skill_dir_name}' description contains angle brackets, stripping for safety")
        description = description.replace("<", "").replace(">", "")

    return description


def _warn_unknown_fields(parsed: dict[str, object], skill_dir_name: str) -> None:
    """Log warnings for unrecognized frontmatter fields."""
    unknown = set(parsed.keys()) - _KNOWN_FRONTMATTER_FIELDS
    if unknown:
        logger.warning(f"Skill '{skill_dir_name}' has unknown frontmatter fields: {', '.join(sorted(unknown))}")


def _parse_requires(parsed: dict[str, object]) -> SkillRequires | None:
    """Parse dependency requirements from frontmatter.

    Args:
        parsed: Parsed YAML frontmatter dict

    Returns:
        SkillRequires if requirements are declared, None otherwise
    """
    raw_requires = parsed.get("requires")
    if not isinstance(raw_requires, dict):
        return None

    bins = _extract_str_list(raw_requires.get("bins"))
    env = _extract_str_list(raw_requires.get("env"))
    config = _extract_str_list(raw_requires.get("config"))

    if not bins and not env and not config:
        return None

    return SkillRequires(bins=bins, env=env, config=config)


def _extract_str_list(value: object) -> list[str]:
    """Extract a list of strings from a YAML value, tolerating various formats."""
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if item is not None and str(item).strip()]
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    return []


def _require_contract_mapping(raw_contract: object, skill_dir_name: str) -> dict[str, object]:
    if not isinstance(raw_contract, dict):
        raise SkillMetadataError(f"Skill '{skill_dir_name}' contract must be a YAML mapping with structured fields")
    return raw_contract


def _parse_contract_steps(raw_contract: dict[str, object], skill_dir_name: str) -> tuple[str, ...]:
    return tuple(_extract_str_list(raw_contract.get("steps")))


def _parse_contract_dependencies(raw_contract: dict[str, object]) -> tuple[str, ...]:
    return tuple(_extract_str_list(raw_contract.get("dependencies")))


def _parse_contract_success_criteria(raw_contract: dict[str, object], skill_dir_name: str) -> str:
    raw_value = raw_contract.get("success_criteria")
    if raw_value is None:
        return ""
    if not isinstance(raw_value, str):
        raise SkillMetadataError(f"Skill '{skill_dir_name}' contract.success_criteria must be a string")
    return raw_value.strip()


def _parse_contract_duration(raw_contract: dict[str, object], skill_dir_name: str) -> float | None:
    import math

    raw_value = raw_contract.get("estimated_duration_seconds")
    if raw_value is None:
        return None
    try:
        duration = float(raw_value)
    except (TypeError, ValueError) as exc:
        raise SkillMetadataError(
            f"Skill '{skill_dir_name}' contract.estimated_duration_seconds must be numeric"
        ) from exc
    if math.isnan(duration) or math.isinf(duration):
        raise SkillMetadataError(f"Skill '{skill_dir_name}' contract.estimated_duration_seconds must be finite")
    if duration < 0:
        raise SkillMetadataError(f"Skill '{skill_dir_name}' contract.estimated_duration_seconds cannot be negative")
    return duration


def _parse_contract_judgments(
    raw_contract: dict[str, object],
    skill_dir_name: str,
) -> tuple[SkillContractJudgment, ...]:
    raw_items = raw_contract.get("key_judgments")
    if raw_items is None:
        return ()
    if not isinstance(raw_items, list):
        raise SkillMetadataError(f"Skill '{skill_dir_name}' contract.key_judgments must be a list")

    judgments: list[SkillContractJudgment] = []
    for index, item in enumerate(raw_items, start=1):
        if not isinstance(item, dict):
            raise SkillMetadataError(f"Skill '{skill_dir_name}' contract.key_judgments[{index}] must be a mapping")
        judgment_id = str(item.get("judgment_id", "")).strip()
        description = str(item.get("description", "")).strip()
        condition = str(item.get("condition", "")).strip()
        true_branch = str(item.get("true_branch", "")).strip()
        false_branch = str(item.get("false_branch", "")).strip()
        if not all((judgment_id, description, condition, true_branch, false_branch)):
            raise SkillMetadataError(
                f"Skill '{skill_dir_name}' contract.key_judgments[{index}] has missing required fields"
            )
        rationale_raw = item.get("rationale")
        rationale = str(rationale_raw).strip() if rationale_raw is not None else None
        judgments.append(
            SkillContractJudgment(
                judgment_id=judgment_id,
                description=description,
                condition=condition,
                true_branch=true_branch,
                false_branch=false_branch,
                rationale=rationale or None,
            )
        )
    return tuple(judgments)


def _parse_contract_traps(
    raw_contract: dict[str, object],
    skill_dir_name: str,
) -> tuple[SkillContractTrap, ...]:
    raw_items = raw_contract.get("potential_traps")
    if raw_items is None:
        return ()
    if not isinstance(raw_items, list):
        raise SkillMetadataError(f"Skill '{skill_dir_name}' contract.potential_traps must be a list")

    traps: list[SkillContractTrap] = []
    for index, item in enumerate(raw_items, start=1):
        if not isinstance(item, dict):
            raise SkillMetadataError(f"Skill '{skill_dir_name}' contract.potential_traps[{index}] must be a mapping")
        description = str(item.get("description", "")).strip()
        mitigation = str(item.get("mitigation", "")).strip()
        if not description or not mitigation:
            raise SkillMetadataError(
                f"Skill '{skill_dir_name}' contract.potential_traps[{index}] requires description and mitigation"
            )
        severity_raw = item.get("severity")
        severity = str(severity_raw).strip() if severity_raw is not None else "medium"
        trigger_raw = item.get("trigger_condition")
        trigger_condition = str(trigger_raw).strip() if trigger_raw is not None else None
        traps.append(
            SkillContractTrap(
                description=description,
                mitigation=mitigation,
                severity=severity or "medium",
                trigger_condition=trigger_condition or None,
            )
        )
    return tuple(traps)


def _parse_contract_verifications(
    raw_contract: dict[str, object],
    skill_dir_name: str,
) -> tuple[SkillContractVerification, ...]:
    raw_items = raw_contract.get("verification_steps")
    if raw_items is None:
        return ()
    if not isinstance(raw_items, list):
        raise SkillMetadataError(f"Skill '{skill_dir_name}' contract.verification_steps must be a list")

    verifications: list[SkillContractVerification] = []
    for index, item in enumerate(raw_items, start=1):
        if not isinstance(item, dict):
            raise SkillMetadataError(f"Skill '{skill_dir_name}' contract.verification_steps[{index}] must be a mapping")
        step_id = str(item.get("step_id", "")).strip()
        description = str(item.get("description", "")).strip()
        validation_method = str(item.get("validation_method", "")).strip()
        if not step_id or not description or not validation_method:
            raise SkillMetadataError(
                f"Skill '{skill_dir_name}' contract.verification_steps[{index}] has missing required fields"
            )
        expected_output_raw = item.get("expected_output")
        expected_output = str(expected_output_raw).strip() if expected_output_raw is not None else None
        verifications.append(
            SkillContractVerification(
                step_id=step_id,
                description=description,
                validation_method=validation_method,
                expected_output=expected_output or None,
                is_required=bool(item.get("is_required", True)),
            )
        )
    return tuple(verifications)


def _parse_skill_contract(parsed: dict[str, object], skill_dir_name: str) -> SkillContract | None:
    raw_contract = parsed.get("contract")
    if raw_contract is None:
        return None

    contract_map = _require_contract_mapping(raw_contract, skill_dir_name)
    return SkillContract(
        steps=_parse_contract_steps(contract_map, skill_dir_name),
        key_judgments=_parse_contract_judgments(contract_map, skill_dir_name),
        potential_traps=_parse_contract_traps(contract_map, skill_dir_name),
        verification_steps=_parse_contract_verifications(contract_map, skill_dir_name),
        dependencies=_parse_contract_dependencies(contract_map),
        estimated_duration_seconds=_parse_contract_duration(contract_map, skill_dir_name),
        success_criteria=_parse_contract_success_criteria(contract_map, skill_dir_name),
    )


def parse_skill_frontmatter(content: str, skill_dir_name: str) -> SkillFrontmatter:
    """Parse YAML frontmatter from SKILL.md (agentskills.io spec compliant).

    Extracts all agentskills.io specification fields plus our extensions:
    - name (optional, max 64 chars, lowercase + hyphens)
    - description (required, truncated to 1024 chars)
    - license (optional)
    - compatibility (optional, truncated to 500 chars)
    - metadata (optional, string key-value pairs)
    - allowed-tools (optional, space-delimited)
    - activation (optional, tags/patterns/exclude-keywords/max-context-tokens)
    - requires (optional, bins/env/config)
    - always (optional, bool)
    - version (optional, string)

    Args:
        content: Full SKILL.md file content
        skill_dir_name: Directory name (for validation and fallback)

    Returns:
        SkillFrontmatter with all parsed fields

    Raises:
        SkillMetadataError: If frontmatter is invalid or missing required fields
    """
    parsed = _parse_frontmatter_yaml(content, skill_dir_name)
    _warn_unknown_fields(parsed, skill_dir_name)
    description = _validate_and_extract_description(parsed, skill_dir_name)

    # name: optional, validate format per agentskills.io spec
    name: str | None = None
    if "name" in parsed:
        raw_name = str(parsed["name"]).strip()
        if len(raw_name) > _MAX_NAME_LENGTH:
            logger.warning(f"Skill '{skill_dir_name}' name exceeds {_MAX_NAME_LENGTH} chars, ignoring")
        else:
            name = raw_name
            if not re.match(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$", raw_name) or "--" in raw_name:
                logger.warning(
                    f"Skill '{skill_dir_name}' name '{raw_name}' does not follow "
                    f"agentskills.io naming convention (lowercase + hyphens only)"
                )

    # license: optional, free-form string
    skill_license: str | None = None
    if "license" in parsed:
        skill_license = str(parsed["license"]).strip() or None

    # compatibility: optional, truncate to 500 chars
    compatibility: str | None = None
    if "compatibility" in parsed:
        compat_raw = str(parsed["compatibility"]).strip()
        if compat_raw:
            if len(compat_raw) > _MAX_COMPATIBILITY_LENGTH:
                logger.warning(
                    f"Skill '{skill_dir_name}' compatibility truncated from "
                    f"{len(compat_raw)} to {_MAX_COMPATIBILITY_LENGTH} chars"
                )
                compat_raw = compat_raw[:_MAX_COMPATIBILITY_LENGTH]
            compatibility = compat_raw

    # metadata: optional, string key-value mapping
    skill_metadata: dict[str, str] = {}
    if "metadata" in parsed and isinstance(parsed["metadata"], dict):
        for k, v in parsed["metadata"].items():
            skill_metadata[str(k)] = str(v)

    # Promote top-level author/homepage into metadata (common convention)
    for key in ("author", "homepage"):
        if key in parsed and key not in skill_metadata:
            raw = str(parsed[key]).strip()
            if raw:
                skill_metadata[key] = raw

    # allowed-tools: optional, space-delimited string
    allowed_tools: str | None = None
    if "allowed-tools" in parsed:
        allowed_tools = str(parsed["allowed-tools"]).strip() or None

    # allowed-domains: optional, list of strings
    allowed_domains: list[str] | None = None
    if "allowed-domains" in parsed:
        allowed_domains = _extract_str_list(parsed.get("allowed-domains"))
        if not allowed_domains:
            allowed_domains = None

    # requires: optional, dependency declaration
    requires = _parse_requires(parsed)

    # Tool-based conditional activation (SKILL.md frontmatter)
    requires_tools = _extract_str_list(parsed.get("requires-tools") or parsed.get("requires_tools"))
    fallback_for_tools = _extract_str_list(parsed.get("fallback-for-tools") or parsed.get("fallback_for_tools"))
    requires_tool_groups = _extract_str_list(
        parsed.get("requires-tool-groups") or parsed.get("requires_tool_groups"),
    )
    fallback_for_tool_groups = _extract_str_list(
        parsed.get("fallback-for-tool-groups") or parsed.get("fallback_for_tool_groups"),
    )

    # always: optional, always-inject flag
    always = bool(parsed.get("always", False))

    # model-invocable: optional (default True)
    # Also supports Claude Code's "disable-model-invocation" (inverted boolean)
    model_invocable = True
    if "model-invocable" in parsed:
        model_invocable = bool(parsed["model-invocable"])
    elif "disable-model-invocation" in parsed:
        model_invocable = not bool(parsed["disable-model-invocation"])

    # user-invocable: optional (default True)
    user_invocable = bool(parsed.get("user-invocable", True))

    # version: optional, version string
    version: str | None = None
    if "version" in parsed:
        raw_version = str(parsed["version"]).strip()
        if raw_version:
            version = raw_version

    # category: optional, for UI grouping
    category: str | None = None
    if "category" in parsed:
        raw_category = str(parsed["category"]).strip()
        if raw_category:
            category = raw_category

    # primaryEnv: optional, primary env var name for apiKey mapping
    # Supports both camelCase (OpenClaw/FastClaw compat) and snake_case
    primary_env: str | None = None
    raw_primary_env = parsed.get("primaryEnv") or parsed.get("primary_env")
    if raw_primary_env:
        pe = str(raw_primary_env).strip()
        if pe:
            primary_env = pe

    # required-credential-files: optional, list of credential file paths
    required_credential_files: list[str] = []
    raw_cred_files = parsed.get("required-credential-files") or parsed.get("required_credential_files")
    if raw_cred_files and isinstance(raw_cred_files, list):
        required_credential_files = [str(f).strip() for f in raw_cred_files if str(f).strip()]

    # credential-env-mapping: optional, dict mapping env vars to credential files
    credential_env_mapping: dict[str, str] = {}
    raw_env_mapping = parsed.get("credential-env-mapping") or parsed.get("credential_env_mapping")
    if raw_env_mapping and isinstance(raw_env_mapping, dict):
        for k, v in raw_env_mapping.items():
            env_name = str(k).strip()
            file_path = str(v).strip()
            if env_name and file_path:
                credential_env_mapping[env_name] = file_path

    # evolution-locked: optional (default False)
    evolution_locked = False
    if "evolution-locked" in parsed:
        evolution_locked = bool(parsed["evolution-locked"])
    elif "evolution_locked" in parsed:
        evolution_locked = bool(parsed["evolution_locked"])

    # config-schema: optional JSON Schema for typed configuration UI
    config_schema: dict[str, object] | None = None
    raw_schema = parsed.get("config-schema") or parsed.get("config_schema")
    if raw_schema and isinstance(raw_schema, dict):
        config_schema = dict(raw_schema)

    # scope_agent_id: optional, agent ID that owns this skill
    scope_agent_id: str | None = None
    if "scope_agent_id" in parsed:
        raw_scope = str(parsed["scope_agent_id"]).strip()
        if raw_scope:
            scope_agent_id = raw_scope

    contract = _parse_skill_contract(parsed, skill_dir_name)

    return SkillFrontmatter(
        description=description,
        name=name,
        license=skill_license,
        compatibility=compatibility,
        metadata=skill_metadata,
        allowed_tools=allowed_tools,
        allowed_domains=allowed_domains,
        requires=requires,
        requires_tools=requires_tools,
        fallback_for_tools=fallback_for_tools,
        requires_tool_groups=requires_tool_groups,
        fallback_for_tool_groups=fallback_for_tool_groups,
        always=always,
        model_invocable=model_invocable,
        user_invocable=user_invocable,
        version=version,
        category=category,
        primary_env=primary_env,
        required_credential_files=required_credential_files,
        credential_env_mapping=credential_env_mapping,
        evolution_locked=evolution_locked,
        config_schema=config_schema,
        contract=contract,
        scope_agent_id=scope_agent_id,
    )


def update_frontmatter_evolution_lock(skill_path: str | Path, locked: bool) -> None:
    """Update the evolution_locked flag in the SKILL.md YAML frontmatter.

    If the field exists, it updates it. If it doesn't exist, it appends it to the end
    of the frontmatter block.

    Args:
        skill_path: Path to the SKILL.md file.
        locked: True to lock, False to unlock.
    """
    path = Path(skill_path)
    if not path.exists():
        return

    content = path.read_text(encoding="utf-8")
    # Match the frontmatter block safely.
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n", content, re.DOTALL)
    if not match:
        logger.warning(f"Failed to find valid YAML frontmatter in {path} to update evolution_locked.")
        return

    frontmatter = match.group(1)

    # Check if evolution_locked or evolution-locked already exists
    pattern = r"^(evolution[-_]locked\s*:\s*)(.*)$"
    if re.search(pattern, frontmatter, re.IGNORECASE | re.MULTILINE):
        # Replace the existing value
        new_frontmatter = re.sub(
            pattern, f"\\g<1>{str(locked).lower()}", frontmatter, flags=re.IGNORECASE | re.MULTILINE
        )
    else:
        # Append to the end of frontmatter
        # Ensure there's exactly one newline before appending
        stripped_fm = frontmatter.rstrip()
        new_frontmatter = stripped_fm + f"\nevolution_locked: {str(locked).lower()}\n"

    # Reconstruct the file content
    new_content = content[: match.start(1)] + new_frontmatter + content[match.end(1) :]
    path.write_text(new_content, encoding="utf-8")
    logger.debug(f"Updated evolution_locked to {locked} in {path}")
