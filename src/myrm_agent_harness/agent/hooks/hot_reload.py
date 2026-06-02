"""Hot-reload support for file-based hook configurations.

[INPUT]
- agent.hooks.types (POS: Hook 定义类型)
- agent.hooks.executor (POS: HookRegistry)

[OUTPUT]
- HookReloader: mtime-based 配置热重载器

[POS]
Hook hot-reload watcher. Monitors JSON/YAML config file changes and auto-reloads hook definitions without agent restart.

"""

from __future__ import annotations

import json
from pathlib import Path

from myrm_agent_harness.agent.hooks.executor import HookRegistry
from myrm_agent_harness.agent.hooks.types import (
    CommandHookDefinition,
    HookDefinition,
    HttpHookDefinition,
    LLMHookDefinition,
)
from myrm_agent_harness.utils.logger_utils import get_agent_logger

logger = get_agent_logger(__name__)

_HOOK_TYPE_MAP: dict[str, type[HookDefinition]] = {
    "command": CommandHookDefinition,
    "http": HttpHookDefinition,
    "llm": LLMHookDefinition,
}


class HookReloader:
    """Reload hook definitions when the settings file changes.

    Checks file mtime_ns on each call to current_registry(). Only reloads
    when the file has actually changed. Returns an empty registry if the
    file is missing or malformed.

    Expected JSON format::

        {
            "hooks": {
                "pre_tool_use": [
                    {"type": "command", "command": "echo $ARGUMENTS", "matcher": "bash_*"},
                    {"type": "http", "url": "https://audit.example.com/hook"}
                ],
                "post_tool_use": [...]
            }
        }
    """

    __slots__ = ("_last_mtime_ns", "_registry", "_settings_path")

    def __init__(self, settings_path: Path) -> None:
        self._settings_path = settings_path
        self._last_mtime_ns: int = -1
        self._registry = HookRegistry()

    def current_registry(self) -> HookRegistry:
        try:
            stat = self._settings_path.stat()
        except FileNotFoundError:
            if self._last_mtime_ns != -1:
                self._registry = HookRegistry()
                self._last_mtime_ns = -1
                logger.info("Hook config file removed, cleared registry")
            return self._registry

        if stat.st_mtime_ns == self._last_mtime_ns:
            return self._registry

        self._last_mtime_ns = stat.st_mtime_ns
        self._registry = _load_registry_from_file(self._settings_path)
        logger.info("Reloaded hook config from %s (%d hooks)", self._settings_path, self._registry.total_count)
        return self._registry


def _load_registry_from_file(path: Path) -> HookRegistry:
    registry = HookRegistry()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Failed to parse hook config %s: %s", path, exc)
        return registry

    hooks_section = raw.get("hooks")
    if not isinstance(hooks_section, dict):
        return registry

    for event_name, hook_list in hooks_section.items():
        if not isinstance(hook_list, list):
            continue
        for hook_data in hook_list:
            if not isinstance(hook_data, dict):
                continue
            hook_type = hook_data.get("type", "")
            definition_cls = _HOOK_TYPE_MAP.get(hook_type)
            if definition_cls is None:
                logger.warning("Unknown hook type '%s' in config, skipping", hook_type)
                continue
            try:
                hook_def = definition_cls.model_validate(hook_data)
                registry.register(event_name, hook_def)
            except Exception as exc:
                logger.warning("Invalid hook definition in %s: %s", path, exc)

    return registry
