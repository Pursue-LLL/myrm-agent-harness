"""Sandbox workspace path remapper for preserving filesystem continuity across environments.

[INPUT]
- standard library re, typing

[OUTPUT]
- SandboxPathRemapper: Path re-anchoring engine mapping host roots to sandbox containers.
- remap_path_string: Pure helper for rewriting individual paths.

[POS]
runtime/context/transcripts/path_remapper.py
Host-to-sandbox path normalization preventing FileNotFoundError during session resume.
"""

from __future__ import annotations


class SandboxPathRemapper:
    """Remaps host-specific absolute paths into container sandbox workspace paths."""

    def __init__(
        self,
        host_root: str | None = None,
        sandbox_root: str = "/workspace",
    ) -> None:
        self._host_root = host_root.rstrip("/\\") if host_root else None
        self._sandbox_root = sandbox_root.rstrip("/\\")

    def remap_text(self, text: str) -> str:
        """Replace occurrences of host_root with sandbox_root in unstructured text."""
        if not self._host_root or not text:
            return text
        return text.replace(self._host_root, self._sandbox_root)

    def remap_arguments(self, args: dict[str, object]) -> dict[str, object]:
        """Deeply transform dict arguments containing path-like keys or host prefixes."""
        if not self._host_root:
            return dict(args)

        remapped: dict[str, object] = {}
        for k, v in args.items():
            if isinstance(v, str):
                remapped[k] = self.remap_text(v)
            elif isinstance(v, list):
                remapped[k] = [self.remap_text(item) if isinstance(item, str) else item for item in v]
            elif isinstance(v, dict):
                # Recurse for nested dictionaries
                remapped[k] = self.remap_arguments(v)  # type: ignore[arg-type]
            else:
                remapped[k] = v
        return remapped


def remap_path_string(path_str: str, host_prefix: str, sandbox_target: str = "/workspace") -> str:
    """Functional utility for single path re-anchoring."""
    remapper = SandboxPathRemapper(host_root=host_prefix, sandbox_root=sandbox_target)
    return remapper.remap_text(path_str)
