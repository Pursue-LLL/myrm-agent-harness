"""Agent Plugins 1.0.0 plugin.json manifest validation.

Implements the closed-schema manifest rules from spec §5 with the exact
self-report-and-ignore semantics:
  - unknown top-level fields        → report + ignore (non-fatal)
  - non-object ``extensions``        → report + ignore (non-fatal)
  - any other schema violation       → fatal (reject the plugin)
  - ``$schema`` version negotiation  → unrecognized version is fatal

[INPUT]
-- .models::AgentPluginManifestMeta (POS: shared parser output dataclasses)

[OUTPUT]
-- decode_manifest_json / parse_manifest: validate plugin.json under the closed
   schema with $schema version negotiation.

[POS]
Closed-schema plugin.json manifest validator for the framework parser.
"""

from __future__ import annotations

import json
import re
from typing import Any

from .models import AgentPluginManifestMeta

# Canonical schema identifiers for the 1.0.0 release (spec §5.2 / §7.2.1).
PLUGIN_SCHEMA = "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"
MCP_SCHEMA = "https://agent-plugins.org/schemas/1.0.0/mcp.schema.json"

_SCHEMA_VERSION_MARKER = "/schemas/"


def schema_version(schema_uri: str) -> str | None:
    """Extract the Agent Plugins version segment from a canonical schema URI.

    plugin.json and mcp.json use different schema URIs (``.../plugin.schema.json``
    vs ``.../mcp.schema.json``) but MUST target the same spec version (§10.1).
    """
    if _SCHEMA_VERSION_MARKER not in schema_uri:
        return None
    return schema_uri.split(_SCHEMA_VERSION_MARKER, 1)[1].split("/", 1)[0]


_SUPPORTED_VERSION_SCHEMAS: frozenset[str] = frozenset({PLUGIN_SCHEMA})

# Allowed top-level fields per the closed manifest schema (§5.2).
_ALLOWED_FIELDS = frozenset(
    {
        "$schema",
        "name",
        "version",
        "description",
        "author",
        "homepage",
        "repository",
        "license",
        "keywords",
        "capabilities",
        "extensions",
    }
)

# §5.5 name constraints.
_NAME_RE = re.compile(r"^(?!.*(?:--|\.\.))[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?$")


class ManifestSchemaError(ValueError):
    """Fatal plugin.json validation error (rejects the whole plugin)."""


class ManifestNoSchemaError(ManifestSchemaError):
    """The manifest's ``$schema`` is missing or unrecognized."""


class ManifestParseError(ValueError):
    """plugin.json is absent, not JSON, or not a top-level object.

    Single unspecified code path: the caller rejects the plugin outright
    (no components). Distinguishable from fatal 'schema violation' errors
    by message, but callers may treat both as ``fatal_manifest``.
    """


class ManifestSchemaValidationError(ValueError):
    """Fatal field-type/constraint violation other than unknown-field handling.

    Carries the offending component code for UI diagnostics.
    """

    def __init__(self, message: str, code: str = "manifest_invalid_field") -> None:
        super().__init__(message)
        self.code = code


def parse_manifest(
    raw: dict[str, Any] | None,
) -> tuple[AgentPluginManifestMeta, list[dict[str, str]]]:
    """Parse a validated manifest dict into metadata plus reported unknown fields.

    Args:
        raw: The parsed top-level JSON object of ``plugin.json``.

    Returns:
        ``(meta, reported_unknown_fields)`` where reported entries are
        ``{"field": name, "message": ...}``.

    Raises:
        ManifestSchemaError: unrecognized/missing ``$schema``.
        ManifestSchemaValidationError: any fatal field violation.
        ManifestParseError: payload is not a JSON object.
    """
    if raw is None:
        raise ManifestParseError("plugin.json is missing or is not a JSON object")

    schema = raw.get("$schema")
    if not isinstance(schema, str) or schema not in _SUPPORTED_VERSION_SCHEMAS:
        raise ManifestNoSchemaError(f"plugin.json declares unsupported or missing $schema: {schema!r}")

    # Required fields (§5.3).
    name = raw.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ManifestSchemaValidationError("plugin.json is missing required field 'name'")
    if not _NAME_RE.match(name):
        raise ManifestSchemaValidationError(
            f"plugin.json 'name' violates Agent Plugins naming constraints: {name!r}",
            code="manifest_invalid_name",
        )

    # Report-and-ignore unknown top-level fields (§5.2).
    reported: list[dict[str, str]] = []
    for field_name in raw:
        if field_name not in _ALLOWED_FIELDS:
            reported.append(
                {
                    "field": field_name,
                    "message": f"Unknown top-level plugin.json field '{field_name}' is ignored",
                }
            )

    # Non-object extensions → report and ignore (§8.1); object → validate contents are objects.
    extensions = raw.get("extensions")
    if extensions is not None and not isinstance(extensions, dict):
        reported.append(
            {
                "field": "extensions",
                "message": "plugin.json 'extensions' is not an object and is ignored",
            }
        )
    elif isinstance(extensions, dict):
        for ns, value in extensions.items():
            if not isinstance(value, dict):
                raise ManifestSchemaValidationError(
                    f"extensions namespace '{ns}' must be an object",
                    code="manifest_invalid_extension",
                )

    version = _optional_str(raw, "version")
    description = _optional_str(raw, "description")
    homepage = _optional_str(raw, "homepage")
    repository = _optional_str(raw, "repository")
    license_ = _optional_str(raw, "license")

    author = _validate_author(raw.get("author"))

    keywords_raw = raw.get("keywords")
    keywords: tuple[str, ...]
    if keywords_raw is None:
        keywords = ()
    elif isinstance(keywords_raw, list) and all(isinstance(k, str) for k in keywords_raw):
        keywords = tuple(keywords_raw)
    else:
        raise ManifestSchemaValidationError("plugin.json 'keywords' must be an array of strings")

    from .models import PluginCapabilityTier

    caps_raw = raw.get("capabilities")
    declared_capabilities: list[PluginCapabilityTier] = []
    if caps_raw is not None:
        if not isinstance(caps_raw, list) or not all(isinstance(c, str) for c in caps_raw):
            raise ManifestSchemaValidationError("plugin.json 'capabilities' must be an array of strings")
        for cap_str in caps_raw:
            try:
                declared_capabilities.append(PluginCapabilityTier(cap_str.lower()))
            except ValueError as err:
                # Disallow unknown capability strings or treat as reportable validation error
                raise ManifestSchemaValidationError(
                    f"plugin.json contains invalid capability '{cap_str}'",
                    code="manifest_invalid_capability",
                ) from err

    meta = AgentPluginManifestMeta(
        name=name,
        version=version,
        description=description,
        author=author,
        homepage=homepage,
        repository=repository,
        license=license_,
        keywords=keywords,
        declared_capabilities=tuple(declared_capabilities),
    )
    return meta, reported


def _optional_str(raw: dict[str, Any], key: str) -> str | None:
    value = raw.get(key)
    if value is None:
        return None
    if isinstance(value, str):
        return value
    raise ManifestSchemaValidationError(f"plugin.json '{key}' must be a string")


def _validate_author(value: object) -> dict[str, str] | None:
    if value is None:
        return None
    if not isinstance(value, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in value.items()):
        raise ManifestSchemaValidationError("plugin.json 'author' must be an object of strings")
    unknown = set(value.keys()) - {"name", "email", "url"}
    if unknown:
        raise ManifestSchemaValidationError(
            f"plugin.json 'author' contains disallowed fields: {sorted(unknown)}",
            code="manifest_invalid_author",
        )
    return {k: v for k, v in value.items()}


def decode_manifest_json(raw: bytes) -> dict[str, Any] | None:
    """Decode plugin.json bytes into a dict, tolerating a UTF-8 BOM.

    Returns ``None`` when the payload is not a JSON object.
    """
    text = raw.decode("utf-8", errors="replace")
    if text.startswith("\ufeff"):
        text = text[1:]
    try:
        decoded = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ManifestParseError(f"plugin.json is not valid JSON: {exc}") from exc
    if isinstance(decoded, dict):
        return decoded
    raise ManifestParseError("plugin.json must be a top-level JSON object")
