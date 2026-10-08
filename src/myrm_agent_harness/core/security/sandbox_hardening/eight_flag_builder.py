"""Builder and verification engine for 8-Flag Docker Sandbox physical hardening."""

from __future__ import annotations

import re

from .types import EightFlagSandboxConfig, HardenedDockerCommand

_SENSITIVE_KEY_PATTERN = re.compile(
    r"(?:^|--env=|-e\s*=?\s*)([A-Za-z0-9_]*(?:TOKEN|KEY|SECRET|PASSWORD|CREDENTIAL)[A-Za-z0-9_]*=)",
    re.IGNORECASE,
)


class EightFlagBuilder:
    """Builds hardened Docker CLI invocation arguments strictly adhering to the 8-flag matrix."""

    def __init__(self, config: EightFlagSandboxConfig | None = None) -> None:
        self.config = config or EightFlagSandboxConfig()

    def build_run_args(
        self,
        image: str,
        command: list[str] | None = None,
        extra_mounts: list[str] | None = None,
    ) -> HardenedDockerCommand:
        """Construct the complete hardened docker run argument list."""
        args: list[str] = ["docker", "run"]

        if self.config.auto_remove:
            args.append("--rm")

        # Flag 1: Read-only root filesystem
        if self.config.read_only:
            args.append("--read-only")

        # Flag 2: /tmp mounted as tmpfs with noexec
        if self.config.tmp_noexec:
            args.append(f"--tmpfs=/tmp:size={self.config.tmp_size_mb}m,noexec")
        else:
            args.append(f"--tmpfs=/tmp:size={self.config.tmp_size_mb}m")

        # Flag 3: PIDs limit to defeat fork-bombs
        args.append(f"--pids-limit={self.config.pids_limit}")

        # Flag 4: Drop all Linux capabilities
        if self.config.cap_drop_all:
            args.append("--cap-drop=ALL")

        # Flag 5: Block privilege escalation
        if self.config.no_new_privileges:
            args.append("--security-opt=no-new-privileges")

        # Flag 6: Non-root execution
        args.append(f"--user={self.config.user}")

        # Flag 7: Network physical air-gap
        args.append(f"--network={self.config.network_mode.value}")

        # Flag 8: Resource bounding
        args.append(f"--memory={self.config.memory_limit}")
        args.append(f"--cpus={self.config.cpus_quota}")

        if extra_mounts:
            for mount in extra_mounts:
                args.extend(["-v", mount])

        args.append(image)

        if command:
            args.extend(command)

        verified, missing = self.verify_flags(args)
        return HardenedDockerCommand(
            raw_args=args,
            flags_verified=verified,
            missing_flags=missing,
        )

    def verify_flags(self, args: list[str]) -> tuple[bool, list[str]]:
        """Verify that all 8 physical hardening flags are present in the argument sequence."""
        joined = " ".join(args)
        missing: list[str] = []

        if "--read-only" not in args:
            missing.append("FLAG_1_READ_ONLY")

        if not any(
            arg.startswith("--tmpfs=/tmp") and "noexec" in arg for arg in args
        ):
            missing.append("FLAG_2_TMPFS_NOEXEC")

        if not any(arg.startswith("--pids-limit=") for arg in args):
            missing.append("FLAG_3_PIDS_LIMIT")

        if "--cap-drop=ALL" not in args and "--cap-drop ALL" not in joined:
            missing.append("FLAG_4_CAP_DROP_ALL")

        if (
            "--security-opt=no-new-privileges" not in args
            and "--security-opt no-new-privileges" not in joined
        ):
            missing.append("FLAG_5_NO_NEW_PRIVILEGES")

        if not any(arg.startswith("--user=") for arg in args):
            missing.append("FLAG_6_NON_ROOT_USER")

        if not any(arg.startswith("--network=") for arg in args):
            missing.append("FLAG_7_NETWORK_ISOLATION")

        if not any(arg.startswith("--memory=") for arg in args) or not any(
            arg.startswith("--cpus=") for arg in args
        ):
            missing.append("FLAG_8_RESOURCE_BOUNDS")

        return len(missing) == 0, missing

    def check_leak_free_env(self, env_args: list[str]) -> tuple[bool, list[str]]:
        """Assert that no sensitive plaintext credentials are being passed via environment arguments."""
        leaks: list[str] = []
        for i, arg in enumerate(env_args):
            match = _SENSITIVE_KEY_PATTERN.search(arg)
            if match:
                leaks.append(match.group(1))
            elif arg in ("-e", "--env") and i + 1 < len(env_args):
                next_arg = env_args[i + 1]
                match_next = _SENSITIVE_KEY_PATTERN.search(next_arg)
                if match_next:
                    leaks.append(match_next.group(1))

        # Deduplicate while preserving order
        unique_leaks: list[str] = []
        for leak in leaks:
            if leak not in unique_leaks:
                unique_leaks.append(leak)

        return len(unique_leaks) == 0, unique_leaks
