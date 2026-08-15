"""MCP stdio runtime parameter resolution — env/cwd extraction + placeholder expansion.

Agent Plugins 1.0.0 (§9) lets bundled stdio MCP servers reference
``${PLUGIN_ROOT}`` / ``${PLUGIN_DATA}`` in ``args`` / ``env`` / ``cwd``. The
launching client is responsible for a single, non-recursive textual expansion
using the plugin's persisted root directories, and for providing the two
reserved environment variables to every plugin subprocess (§9.1).

This module owns that expansion for the MCP runtime:
- ``expand_placeholders`` — one-pass, non-recursive expansion of the two
  whitelisted placeholders. Any other ``${...}`` token is left untouched
  (unknown variables must never be dropped or substituted).
- ``resolve_stdio_launch`` — resolves the full (command, args, env, cwd) launch
  tuple for a stdio server, reading ``env``/``cwd``/plugin roots from
  ``extra_params``, expanding placeholders everywhere they are legal, and
  injecting ``PLUGIN_ROOT`` / ``PLUGIN_DATA`` into the subprocess environment
  when the corresponding plugin root is configured (§9.1).

Security model: only ``PLUGIN_ROOT`` / ``PLUGIN_DATA`` are expanded, expansion
is a single textual pass (no recursion, no re-expansion of substituted values),
and the substituted roots are taken from the trusted configuration, never from
the plugin-controlled value itself. The reserved environment variables are
client-injected exactly as the spec requires; the Agent Plugins parser already
rejects server ``env`` declarations that name them (§7.2.2), so injection never
overrides a plugin-declared entry.

[INPUT]
- ``config_scan._extract_env_map`` convention: ``extra_params["env"]`` is a
  ``dict[str, str]`` (POS: static/runtime MCP scanners).
- ``config.py::MCPConfig.extra_params`` (POS: MCP Configuration).

[OUTPUT]
- ``expand_placeholders``: one-pass placeholder expansion for a single value.
- ``resolve_stdio_launch``: (command, args, env, cwd) launch tuple for stdio.

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
        str(plugin_root) if isinstance(plugin_root, str) and plugin_root else None,
        str(data_root) if isinstance(data_root, str) and data_root else None,
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
    - When the plugin root is configured, ``PLUGIN_ROOT`` and ``PLUGIN_DATA``
      are injected into the subprocess environment so bundled server scripts
      can locate their package and persistent data directory (§9.1). Each
      variable is injected independently for whichever root is configured.
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
                if val is not None and val != ""
            }
            if expanded:
                env = expanded

    if plugin_root is not None or data_root is not None:
        # Client-provided reserved variables (§9.1): the parser already rejects
        # plugin env declarations naming these keys, so this cannot clobber a
        # legitimate plugin entry.
        if env is None:
            env = {}
        if plugin_root is not None:
            env["PLUGIN_ROOT"] = plugin_root
        if data_root is not None:
            env["PLUGIN_DATA"] = data_root

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
