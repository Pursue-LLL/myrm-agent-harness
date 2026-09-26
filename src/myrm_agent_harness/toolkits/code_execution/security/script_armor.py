"""Script armor suite — file-backed subprocess invocation & quote/syntax escaping armor.

[INPUT]
- None (POS: Zero-dependency leaf utility module in security toolkit)

[OUTPUT]
- ScriptArmorConfig: Dataclass configuring direct execution thresholds
- ArmoredCommandString: String subclass carrying is_armored execution tag
- should_materialize_script: Dual-mode heuristic decision probe
- materialize_script_to_file: Atomic 0700 script file creation
- build_file_backed_command: Subshell invocation command formatter
- cleanup_materialized_script: Safe file unlink cleanup
- sweep_stale_materialized_scripts: Safe cleanup of stale orphan materialized scripts
- prepare_armored_command: Context manager wrapping materialization, execution, and cleanup

[POS]
Execution security armor. Protects persistent sessions against beacon swallowing,
exit-statement process deaths, and quote bombs by materializing complex scripts to
secured temporary files executed via subshells, while preserving the direct execution
fast-path for session state modifiers (cd, export, source).
"""

from __future__ import annotations

import contextlib
import dataclasses
import logging
import os
import re
import uuid
from collections.abc import Iterator
from pathlib import Path

logger: logging.Logger = logging.getLogger(__name__)

# Fast-path commands that must execute directly in the parent persistent shell
# to preserve session-level state (directory changes, environment variables).
_PARENT_STATE_PREFIXES: tuple[str, ...] = (
    "cd ",
    "cd\t",
    "pushd ",
    "pushd\t",
    "popd",
    "export ",
    "export\t",
    "unset ",
    "unset\t",
    "source ",
    "source\t",
    ". ",
    ".\t",
)

# Regex to detect heredoc patterns (e.g. <<EOF, <<'EOF', <<-"EOF")
_HEREDOC_PATTERN: re.Pattern[str] = re.compile(r"<<-?\s*['\"]?[A-Za-z0-9_]+['\"]?")

# Regex to detect top-level exit commands that could terminate the parent persistent shell
_EXIT_PATTERN: re.Pattern[str] = re.compile(r"(?:^|[;&|\s])exit(?:\s+[0-9]+)?(?:\s*[;&|]|\s*$)")


@dataclasses.dataclass(frozen=True, slots=True)
class ScriptArmorConfig:
    """Configuration options for script materialization armor."""

    enabled: bool = True
    direct_max_bytes: int = 512
    max_direct_lines: int = 2
    temp_dir: str = "/tmp"
    script_prefix: str = ".myrm_exec_"


class ArmoredCommandString(str):
    """String subclass tagging armored subshell execution status.

    Behaves identically to a normal ``str`` for all operations, but carries an
    ``is_armored: bool`` attribute indicating whether the command was materialized
    to a file-backed subshell.
    """

    is_armored: bool

    def __new__(cls, value: str, is_armored: bool = False) -> ArmoredCommandString:
        obj = super().__new__(cls, value)
        obj.is_armored = is_armored
        return obj


def should_materialize_script(command: str, config: ScriptArmorConfig | None = None) -> bool:
    """Determine whether *command* should be materialized to a file and run in a subshell.

    Returns False (Direct Fast-Path) for:
      - Parent state modifying commands: cd, pushd, popd, export, unset, source, .
      - Simple short single-line commands (e.g. ls, git status, echo $VAR) without heredocs,
        nested exit statements, or unbalanced syntax blocks.

    Returns True (File-Backed Armor) for:
      - Multiline commands (> max_direct_lines)
      - Commands containing heredoc syntax (<<EOF)
      - Commands containing exit statements (which would kill the parent shell)
      - Commands exceeding direct_max_bytes
    """
    if config is None:
        config = ScriptArmorConfig()

    if not config.enabled:
        return False

    stripped: str = command.strip()
    if not stripped:
        return False

    # Check for direct state modifiers first.
    # If the entire command is a single-line parent state modification, keep it in parent shell.
    lines: list[str] = [line for line in stripped.splitlines() if line.strip()]
    if len(lines) <= 1:
        for prefix in _PARENT_STATE_PREFIXES:
            # Single-line state modifications must run directly in the parent shell
            # so environment variables and directory changes persist in the session.
            if stripped.startswith(prefix) or stripped == prefix.strip():
                return False

    # Check line count
    if len(lines) > config.max_direct_lines:
        return True

    # Check byte size
    if len(command.encode("utf-8", errors="replace")) > config.direct_max_bytes:
        return True

    # Check for heredocs (<<EOF or <<'EOF')
    if _HEREDOC_PATTERN.search(command):
        return True

    # Check for exit statements that could kill the persistent parent process
    return bool(_EXIT_PATTERN.search(command))


def materialize_script_to_file(
    command: str,
    temp_dir: str | Path = "/tmp",
    prefix: str = ".myrm_exec_",
) -> Path:
    """Atomically write *command* to a secured temporary executable shell script.

    File permissions are explicitly set to 0700 (owner read, write, execute only).
    """
    target_dir: Path = Path(temp_dir)
    target_dir.mkdir(parents=True, exist_ok=True)

    unique_id: str = uuid.uuid4().hex
    script_path: Path = target_dir / f"{prefix}{unique_id}.sh"

    # Use os.open with O_CREAT | O_WRONLY | O_EXCL to prevent symlink attacks and race conditions
    fd: int = os.open(str(script_path), os.O_CREAT | os.O_WRONLY | os.O_EXCL, 0o700)
    try:
        content: str = command if command.endswith("\n") else command + "\n"
        with open(fd, "w", encoding="utf-8", closefd=True) as f:
            f.write(content)
    except Exception:
        with contextlib.suppress(OSError):
            os.close(fd)
        script_path.unlink(missing_ok=True)
        raise

    return script_path


def build_file_backed_command(script_path: str | Path, shell_bin: str = "bash") -> str:
    """Build the subshell execution command string for *script_path*."""
    resolved_path: str = str(Path(script_path).resolve())
    return f'{shell_bin} "{resolved_path}"'


def cleanup_materialized_script(script_path: str | Path | None) -> None:
    """Safely unlink the temporary script file."""
    if script_path is None:
        return
    with contextlib.suppress(OSError):
        Path(script_path).unlink(missing_ok=True)


def sweep_stale_materialized_scripts(
    temp_dir: str | Path = "/tmp",
    max_age_seconds: float = 3600.0,
    prefix: str = ".myrm_exec_",
) -> int:
    """Scan *temp_dir* and safely unlink stale materialized script files.

    Used during session initialization or periodic maintenance to clean up
    orphan scripts left behind by ungraceful terminations (e.g. OOM-kill).
    Returns the number of files cleaned.
    """
    cleaned: int = 0
    dir_path: Path = Path(temp_dir)
    if not dir_path.is_dir():
        return 0

    import time

    now: float = time.time()
    try:
        for p in dir_path.glob(f"{prefix}*.sh"):
            try:
                if (now - p.stat().st_mtime) > max_age_seconds:
                    p.unlink(missing_ok=True)
                    cleaned += 1
            except OSError:
                pass
    except OSError:
        pass
    return cleaned


@contextlib.contextmanager
def prepare_armored_command(
    command: str,
    work_dir: str | Path = "/tmp",
    is_windows: bool = False,
    config: ScriptArmorConfig | None = None,
) -> Iterator[str]:
    """Context manager to optionally materialize complex scripts to a temporary file.

    Executes complex scripts via child subshell, while preserving direct parent shell
    execution for directory changes, environment variable exports, and simple short commands.
    Yields an ArmoredCommandString carrying is_armored=True when materialized, False otherwise.
    """
    if is_windows or not should_materialize_script(command, config):
        yield ArmoredCommandString(command, is_armored=False)
        return

    materialized_path: Path | None = None
    try:
        target_dir: Path = Path(work_dir) if Path(work_dir).is_dir() else Path("/tmp")
        materialized_path = materialize_script_to_file(command, temp_dir=target_dir)
        yield ArmoredCommandString(build_file_backed_command(materialized_path), is_armored=True)
    except Exception as e:
        logger.warning("Script materialization failed, fallback to direct: %s", e)
        yield ArmoredCommandString(command, is_armored=False)
    finally:
        cleanup_materialized_script(materialized_path)
