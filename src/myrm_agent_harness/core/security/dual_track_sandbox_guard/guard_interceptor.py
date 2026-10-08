"""Sandbox Execution Interceptor enforcing physical barriers and defense-in-depth against evasion.

[INPUT]
- File path candidates, shell command lines, and soft memory queries.

[OUTPUT]
- ExecutionInterceptionVerdict determining whether execution proceeds to sandbox syscall/process table.

[POS]
- Harness core security interceptor enforcing the rule that instructions are not permissions.
"""

from __future__ import annotations

import base64
import re
import urllib.parse
import uuid
from typing import Final

from myrm_agent_harness.core.security.dual_track_sandbox_guard.policy_compiler import (
    RedlinePolicyCompiler,
)
from myrm_agent_harness.core.security.dual_track_sandbox_guard.types import (
    ExecutionInterceptionVerdict,
    InterceptionVerdict,
    SoftMemoryRecord,
)

_BASE64_PIPE_REGEX: Final[re.Pattern[str]] = re.compile(
    r"(?:echo|printf)\s+['\"]?([A-Za-z0-9+/=]{8,})['\"]?\s*\|\s*(?:base64\s+-d|base64\s+--decode)\s*\|\s*(?:bash|sh|zsh)",
    re.IGNORECASE,
)

_PROTECTED_KEYWORDS: Final[tuple[str, ...]] = (
    ".env",
    "id_rsa",
    "/etc/shadow",
    ".pem",
)


class DualTrackSandboxGuard:
    """Enforces non-bypassable physical interception of file access and commands."""

    def __init__(self, compiler: RedlinePolicyCompiler | None = None) -> None:
        self._compiler = compiler or RedlinePolicyCompiler()

    @property
    def compiler(self) -> RedlinePolicyCompiler:
        """Access underlying policy compiler."""
        return self._compiler

    def evaluate_file_access(
        self, file_path: str, operation: str = "read"
    ) -> ExecutionInterceptionVerdict:
        """Intercept and evaluate target file access against compiled physical policy."""
        audit_id = f"grd-file-{uuid.uuid4().hex[:10]}"

        # Evasion check: URL-encoded traversal or null bytes
        decoded_path = urllib.parse.unquote(file_path)
        if "\x00" in file_path or "\x00" in decoded_path:
            return ExecutionInterceptionVerdict(
                verdict=InterceptionVerdict.BLOCKED_EVASION_ATTEMPT,
                is_permitted=False,
                blocked_by_rule_id=None,
                target_operation=f"{operation}:{file_path}",
                audit_id=audit_id,
                rationale="Null byte poison path evasion attempt detected.",
            )

        norm_path = decoded_path.replace("\\", "/")

        # Match against compiled rules
        for rule in self._compiler.get_all_rules():
            if (
                rule.category.value == "FILE_PROTECTION"
                and RedlinePolicyCompiler.matches_file_pattern(norm_path, rule.pattern)
            ):
                return ExecutionInterceptionVerdict(
                    verdict=InterceptionVerdict.BLOCKED_HARD_REDLINE_FILE,
                    is_permitted=False,
                    blocked_by_rule_id=rule.rule_id,
                    target_operation=f"{operation}:{file_path}",
                    audit_id=audit_id,
                    rationale=f"Sandbox physical firewall blocked file access matching '{rule.pattern}' ({rule.description}).",
                )

        return ExecutionInterceptionVerdict(
            verdict=InterceptionVerdict.PERMITTED,
            is_permitted=True,
            blocked_by_rule_id=None,
            target_operation=f"{operation}:{file_path}",
            audit_id=audit_id,
            rationale="File access authorized by sandbox execution guard.",
        )

    def evaluate_command_execution(self, command: str) -> ExecutionInterceptionVerdict:
        """Intercept and evaluate shell command candidates prior to container process spawning."""
        audit_id = f"grd-cmd-{uuid.uuid4().hex[:10]}"
        cmd_stripped = command.strip()

        # 1. Defense-in-depth: check base64 obfuscation pipe evasions
        b64_match = _BASE64_PIPE_REGEX.search(cmd_stripped)
        if b64_match:
            encoded_payload = b64_match.group(1)
            try:
                decoded_bytes = base64.b64decode(encoded_payload, validate=True)
                decoded_str = decoded_bytes.decode("utf-8", errors="ignore").lower()
                for keyword in _PROTECTED_KEYWORDS:
                    if keyword in decoded_str:
                        return ExecutionInterceptionVerdict(
                            verdict=InterceptionVerdict.BLOCKED_EVASION_ATTEMPT,
                            is_permitted=False,
                            blocked_by_rule_id=None,
                            target_operation=cmd_stripped,
                            audit_id=audit_id,
                            rationale=f"Obfuscated base64 execution evasion detected targeting protected keyword '{keyword}'.",
                        )
            except Exception:
                pass

        # 2. Command pattern regex check
        for rule in self._compiler.get_all_rules():
            if (
                rule.category.value == "COMMAND_PROTECTION"
                and RedlinePolicyCompiler.matches_command_pattern(cmd_stripped, rule.pattern)
            ):
                return ExecutionInterceptionVerdict(
                    verdict=InterceptionVerdict.BLOCKED_HARD_REDLINE_COMMAND,
                    is_permitted=False,
                    blocked_by_rule_id=rule.rule_id,
                    target_operation=cmd_stripped,
                    audit_id=audit_id,
                    rationale=f"Sandbox physical firewall blocked destructive command matching rule {rule.rule_id}: {rule.description}",
                )

        # 3. Direct access to protected file within command
        for rule in self._compiler.get_all_rules():
            if rule.category.value == "FILE_PROTECTION":
                tokens = re.split(r"[\s;|>&<]+", cmd_stripped)
                for token in tokens:
                    if RedlinePolicyCompiler.matches_file_pattern(token, rule.pattern):
                        return ExecutionInterceptionVerdict(
                            verdict=InterceptionVerdict.BLOCKED_HARD_REDLINE_FILE,
                            is_permitted=False,
                            blocked_by_rule_id=rule.rule_id,
                            target_operation=cmd_stripped,
                            audit_id=audit_id,
                            rationale=f"Command references protected file target '{token}' governed by {rule.rule_id}.",
                        )

        return ExecutionInterceptionVerdict(
            verdict=InterceptionVerdict.PERMITTED,
            is_permitted=True,
            blocked_by_rule_id=None,
            target_operation=cmd_stripped,
            audit_id=audit_id,
            rationale="Command execution authorized by sandbox execution guard.",
        )

    @classmethod
    def filter_soft_memories(
        cls, memories: list[SoftMemoryRecord], min_weight: float = 0.2
    ) -> list[SoftMemoryRecord]:
        """Query and decay soft experience memories, maintaining pure cognitive separation."""
        retained: list[SoftMemoryRecord] = []
        for mem in memories:
            if mem.compute_effective_weight() >= min_weight:
                retained.append(mem)
        return retained
