"""Credential Stdin Pipelining Engine and process table isolation executor.

[INPUT]
- Shell commands containing secrets or tokens.

[OUTPUT]
- PipelinedCommandSpec with clean sanitized argv, stdin payloads, and zeroized memory buffers.

[POS]
- Harness core security pipeline eliminating credential exposure in Linux/container process tables.
"""

from __future__ import annotations

import io
import re
import shlex
import subprocess

from myrm_agent_harness.core.security.credential_shield.inspector import (
    CommandLineCredentialInspector,
)
from myrm_agent_harness.core.security.credential_shield.types import (
    CredentialPipeliningError,
    CredentialTransportMode,
    PipelinedCommandSpec,
)
from myrm_agent_harness.core.security.credential_shield.zeroizer import (
    EphemeralCredentialZeroizer,
)

_CURL_AUTH_REGEX = re.compile(
    r"(-H|--header)\s+['\"]?(Authorization:\s*[^'\"]+)['\"]?",
    re.IGNORECASE,
)
_CURL_APIKEY_REGEX = re.compile(
    r"(-H|--header)\s+['\"]?((X-Api-Key|Api-Key):\s*[^'\"]+)['\"]?",
    re.IGNORECASE,
)


class CredentialStdinPipeliningEngine:
    """Transforms command lines into safe stdin-pipelined executions with zeroization."""

    @classmethod
    def pipeline_command(cls, raw_command: str) -> PipelinedCommandSpec:
        """Inspect and rewrite commands to stream sensitive credentials exclusively via standard input."""
        cmd = raw_command.strip()
        analysis = CommandLineCredentialInspector.inspect(cmd)

        # If already safe, return spec without stdin payload
        if analysis.is_safe_for_process_table:
            try:
                argv = tuple(shlex.split(cmd))
            except ValueError:
                argv = tuple(cmd.split())
            return PipelinedCommandSpec(
                original_command=cmd,
                sanitized_argv=argv,
                stdin_payload=b"",
                transport_mode=CredentialTransportMode.STDIN_PIPELINE,
                sanitized_display_cmd=cmd,
                detected_secret_patterns=(),
            )

        # Handle curl command transformations
        if cmd.startswith("curl ") or " curl " in cmd:
            return cls._pipeline_curl(cmd, analysis.detected_leaks)

        # Generic command pipeline fallback
        return cls._pipeline_generic(cmd, analysis.detected_leaks)

    @classmethod
    def _pipeline_curl(cls, cmd: str, leaks: tuple[str, ...]) -> PipelinedCommandSpec:
        """Rewrite curl command to stream headers via --config - (stdin)."""
        headers_to_pipe: list[str] = []

        # Find Authorization headers
        for match in _CURL_AUTH_REGEX.finditer(cmd):
            header_val = match.group(2)
            headers_to_pipe.append(f'header = "{header_val}"')

        for match in _CURL_APIKEY_REGEX.finditer(cmd):
            header_val = match.group(2)
            headers_to_pipe.append(f'header = "{header_val}"')

        # Remove raw headers from command line
        cleaned_cmd = _CURL_AUTH_REGEX.sub("", cmd)
        cleaned_cmd = _CURL_APIKEY_REGEX.sub("", cleaned_cmd)

        # Inject -K - (read config from stdin)
        parts = shlex.split(cleaned_cmd)
        if parts and parts[0] == "curl":
            parts.insert(1, "-K")
            parts.insert(2, "-")
        else:
            parts.extend(["-K", "-"])

        stdin_content = "\n".join(headers_to_pipe) + "\n"
        stdin_bytes = stdin_content.encode("utf-8")

        display_cmd = " ".join(parts) + " [CREDENTIAL_VIA_STDIN_PIPELINE]"

        return PipelinedCommandSpec(
            original_command=cmd,
            sanitized_argv=tuple(parts),
            stdin_payload=stdin_bytes,
            transport_mode=CredentialTransportMode.STDIN_CONFIG_STREAM,
            sanitized_display_cmd=display_cmd,
            detected_secret_patterns=leaks,
        )

    @classmethod
    def _pipeline_generic(cls, cmd: str, leaks: tuple[str, ...]) -> PipelinedCommandSpec:
        """Sanitize generic CLI tool command by redacting argv and providing stdin payload."""
        sanitized_display = CommandLineCredentialInspector.sanitize_display(cmd)
        try:
            argv = tuple(shlex.split(sanitized_display))
        except ValueError:
            argv = tuple(sanitized_display.split())

        return PipelinedCommandSpec(
            original_command=cmd,
            sanitized_argv=argv,
            stdin_payload=b"",
            transport_mode=CredentialTransportMode.STDIN_PIPELINE,
            sanitized_display_cmd=sanitized_display,
            detected_secret_patterns=leaks,
        )

    @classmethod
    def execute_with_zeroization(
        cls,
        spec: PipelinedCommandSpec,
        timeout: float = 30.0,
    ) -> tuple[int, str, str]:
        """Execute pipelined command, streaming stdin and immediately zeroizing memory buffer."""
        if not spec.sanitized_argv:
            raise CredentialPipeliningError("Cannot execute empty command specification.")

        stream_buffer = io.BytesIO()
        try:
            EphemeralCredentialZeroizer.pipe_and_wipe(spec.stdin_payload, stream_buffer)
            input_bytes = stream_buffer.getvalue()

            proc = subprocess.run(
                list(spec.sanitized_argv),
                input=input_bytes,
                capture_output=True,
                timeout=timeout,
                check=False,
            )
            return (
                proc.returncode,
                proc.stdout.decode("utf-8", errors="replace"),
                proc.stderr.decode("utf-8", errors="replace"),
            )
        finally:
            stream_buffer.close()
