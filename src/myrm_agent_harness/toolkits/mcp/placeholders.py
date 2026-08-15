"""MCP stdio runtime parameter resolution — env/cwd extraction + placeholder expansion.

Agent Plugins 1.0.0 (§9.2) lets bundled stdio MCP servers reference
``${PLUGIN_ROOT}`` / ``${PLUGIN_DATA}`` in ``args`` / ``env`` / ``cwd``. The
launching client is responsible for a single, non-recursive textual expansion
using the plugin's persisted root directories.

This module owns that expansion for the MCP runtime:
- ``expand_placeholders`` — one-pass, non-recursive expansion of the two
  whitelisted placeholders. Any other ``${...}`` token is left untouched
  (unknown variables must never be dropped or substituted).
- ``resolve_stdio_launch`` — resolves the full (command, args, env, cwd) launch
  tuple for a stdio server, reading ``env``/``cwd``/plugin roots from
  ``extra_params`` and expanding placeholders everywhere they are legal.
- ``resolve_stdio_params`` — compatibility helper returning only (env, cwd).

Security model: only ``PLUGIN_ROOT`` / ``PLUGIN_DATA`` are expanded, expansion
is a single textual pass (no recursion, no re-expansion of substituted values),
and the substituted roots are taken from the trusted configuration, never from
the plugin-controlled value itself.

[INPUT]
- ``config_scan._extract_env_map`` convention: ``extra_params["env"]`` is a
  ``dict[str, str]`` (POS: static/runtime MCP scanners).
- ``config.py::MCPConfig.extra_params`` (POS: MCP Configuration).

[OUTPUT]
- ``expand_placeholders``: one-pass placeholder expansion for a single value.
- ``resolve_stdio_launch``: (command, args, env, cwd) launch tuple for stdio.
- ``resolve_stdio_params``: (env, cwd) launch tuple (compat helper).

[POS]
Framework-level MCP runtime parameter resolution. Plain functions, no agent or
business coupling — reusable by the connection pool, one-shot enumeration, and
any future transport.
"""

from __future__ import annotations

import re

_EnvDict = dict[str, str]

_PLACEHOLDER_PATTERN = re.compile(r"\$\{(PLUGIN_ROOT|PLUGIN_DATA)\}")
# Allowed extra_params keys carrying the plugin root directories.
_PLUGIN_ROOT_KEY = "plugin_root"
_DATA_ROOT_KEY = "data_root"


def expand_placeholders(
    value: str,
    *,
    plugin_root: str | None = None,
    data_root: str | None = None,
) -> str:
    """Expand ``${PLUGIN_ROOT}`` / ``${PLUGIN_DATA}`` in ``value`` in one pass.

    Only the two whitelisted placeholders are substituted; every other
    ``${...}`` token is preserved verbatim. When a referenced root is not
    configured the placeholder is left as-is so the failure is visible at
    spawn time instead of silently producing a mangled path.
    """
    if "${" not in value:
        return value
    roots = {"PLUGIN_ROOT": plugin_root, "PLUGIN_DATA": data_root}

    def _replace(match: re.Match[str]) -> str:
        root = roots.get(match.group(1))
        return root if root is not None else match.group(0)

    return _PLACEHOLDER_PATTERN.sub(_replace, value)


def _root_dirs(extra_params: dict[str, object] | None) -> tuple[str | None, str | None]:
    if not extra_params:
        return None, None
    plugin_root = extra_params.get(_PLUGIN_ROOT_KEY)
    data_root = extra_params.get(_DATA_ROOT_KEY)
    return (
        str(plugin_root) if isinstance(plugin_root, str) else None,
        str(data_root) if isinstance(data_root, str) else None,
    )


def resolve_stdio_launch(
    command: str | None,
    args: list[str] | None,
    extra_params: dict[str, object] | None,
) -> tuple[str, list[str], _EnvDict | None, str | None]:
    """Resolve the full stdio launch tuple ``(command, args, env, cwd)``.

    - ``env`` / ``cwd`` are read from ``extra_params`` (the only place they
      live) and have placeholders expanded.
    - ``args`` (from the config top level) get placeholders expanded too.
    - ``cwd`` of ``./`` is the plugin-root-relative form and resolves to
      ``plugin_root`` when configured; a stdio ``command`` starting with
      ``./`` (a plugin-relative executable) implies the same cwd when the
      plugin did not declare one.

    ``command`` itself is never expanded — the Agent Plugins parser only
    accepts bare tokens or ``./``-relative paths, and shell interpolation of
    the executable name is not permitted.
    """
    plugin_root, data_root = _root_dirs(extra_params)

    env: _EnvDict | None = None
    if extra_params:
        raw_env = extra_params.get("env")
        if isinstance(raw_env, dict):
            expanded = {
                str(key): expand_placeholders(
                    str(val), plugin_root=plugin_root, data_root=data_root
                )
                for key, val in raw_env.items()
                if val is not None
            }
            if expanded:
                env = expanded

    cwd: str | None = None
    if extra_params:
        raw_cwd = extra_params.get("cwd")
        if isinstance(raw_cwd, str) and raw_cwd:
            cwd = raw_cwd
    if cwd == "./" and plugin_root is not None:
        cwd = plugin_root
    elif cwd is not None:
        cwd = expand_placeholders(cwd, plugin_root=plugin_root, data_root=data_root)

    # A ./-relative executable runs from the plugin root even when no cwd was
    # declared (command == "./bin/foo" is a plugin-relative path per §7.2.1).
    if cwd is None and command is not None and command.startswith("./") and plugin_root is not None:
        cwd = plugin_root

    expanded_args = (
        [expand_placeholders(a, plugin_root=plugin_root, data_root=data_root) for a in args]
        if args
        else None
    )
    return command or "", expanded_args or [], env, cwd


def resolve_stdio_params(
    extra_params: dict[str, object] | None,
) -> tuple[dict[str, str] | None, str | None]:
    """Resolve the launch-time (env, cwd) pair for a stdio MCP server.

    Kept as a narrow helper for call sites that only need env/cwd.
    """
    if not extra_params:
        return None, None
    _, _, env, cwd = resolve_stdio_launch(None, None, extra_params)
    return env, cwd
