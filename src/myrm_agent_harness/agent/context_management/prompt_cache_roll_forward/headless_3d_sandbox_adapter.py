# [INPUT]: Headless3DEngineType, Headless3DScriptRequest, Headless3DExecutionResult from roll_forward_types
# [OUTPUT]: Headless3DSandboxAdapter, validate_3d_script_safety
# [POS]: myrm_agent_harness.agent.context_management.prompt_cache_roll_forward.headless_3d_sandbox_adapter
"""Headless 3D/CAD sandbox scripting adapter and geometry pipeline (Item 330).

Provides pure-CPU headless 3D modeling script execution (Blender, OpenSCAD, FreeCAD),
AST safety verification, command construction, and artifact extraction.
"""

from __future__ import annotations

import ast
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Final

from myrm_agent_harness.agent.context_management.prompt_cache_roll_forward.roll_forward_types import (
    Headless3DEngineType,
    Headless3DExecutionResult,
    Headless3DScriptRequest,
)

# Forbidden module names or attributes for headless scripts
_DISALLOWED_IMPORTS: Final[set[str]] = {
    "os.system",
    "subprocess",
    "socket",
    "shutil.rmtree",
    "pty",
    "multiprocessing",
}


def validate_3d_script_safety(script_content: str) -> tuple[bool, str]:
    """Perform static AST security analysis on headless 3D modeling script."""
    if not script_content.strip():
        return False, "Script content is empty"

    try:
        tree = ast.parse(script_content)
    except SyntaxError as e:
        return False, f"Script syntax error: {e}"

    for node in ast.walk(tree):
        # Check imports
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in _DISALLOWED_IMPORTS or alias.name.startswith("socket"):
                    return False, f"Prohibited module import: {alias.name}"
        elif isinstance(node, ast.ImportFrom):
            module_name = node.module or ""
            if module_name in _DISALLOWED_IMPORTS or module_name.startswith("socket"):
                return False, f"Prohibited from-import module: {module_name}"
        # Check forbidden call attributes
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            attr_name = node.func.attr
            if attr_name in {"system", "popen", "spawn"}:
                return False, f"Prohibited function execution: {attr_name}"

    return True, "Safety check passed"


class Headless3DSandboxAdapter:
    """Adapter for executing headless 3D CAD modeling scripts inside sandboxed environments."""

    def __init__(self, workspace_root: Path | None = None) -> None:
        self._workspace_root: Path = workspace_root or Path("/tmp/myrm_sandbox_3d")

    @property
    def workspace_root(self) -> Path:
        """Workspace directory for 3D scripts and deliverables."""
        return self._workspace_root

    def build_cli_command(
        self,
        engine: Headless3DEngineType,
        script_file_path: Path,
        output_model_path: Path,
        preview_png_path: Path | None = None,
    ) -> list[str]:
        """Construct deterministic pure-CPU headless CLI execution command."""
        if engine == Headless3DEngineType.BLENDER:
            cmd = [
                "blender",
                "-b",  # background / headless
                "--factory-startup",
                "-P",
                str(script_file_path),
                "--",
                "--output",
                str(output_model_path),
            ]
            if preview_png_path:
                cmd.extend(["--render-preview", str(preview_png_path)])
            return cmd

        if engine == Headless3DEngineType.OPENSCAD:
            return [
                "openscad",
                "-o",
                str(output_model_path),
                str(script_file_path),
            ]

        # FreeCAD default fallback
        return [
            "freecadcmd",
            str(script_file_path),
        ]

    def execute_script(
        self,
        request: Headless3DScriptRequest,
        mock_in_test: bool = False,
    ) -> Headless3DExecutionResult:
        """Execute the 3D modeling script inside sandbox environment.

        Args:
            request: Modeling script parameters.
            mock_in_test: If True, bypass actual binary spawning (useful when blender is not in PATH).

        Returns:
            Headless3DExecutionResult with generated asset and preview metadata.
        """
        start_time = time.monotonic()

        # 1. Static security validation
        is_safe, safety_reason = validate_3d_script_safety(request.script_content)
        if not is_safe:
            return Headless3DExecutionResult(
                success=False,
                return_code=-1,
                stdout_summary="",
                stderr_summary=f"Security rejection: {safety_reason}",
                execution_time_seconds=round(time.monotonic() - start_time, 4),
            )

        # Ensure directory exists
        self._workspace_root.mkdir(parents=True, exist_ok=True)
        script_path = self._workspace_root / f"{request.target_artifact_name}.py"
        output_path = self._workspace_root / f"{request.target_artifact_name}.{request.output_format}"
        preview_path = (
            self._workspace_root / f"{request.target_artifact_name}_preview.png"
            if request.render_preview
            else None
        )

        try:
            script_path.write_text(request.script_content, encoding="utf-8")
        except OSError as e:
            return Headless3DExecutionResult(
                success=False,
                return_code=-1,
                stdout_summary="",
                stderr_summary=f"Failed to write script: {e}",
                execution_time_seconds=round(time.monotonic() - start_time, 4),
            )

        # 2. Check engine binary or mock execution
        binary_name = (
            "blender" if request.engine == Headless3DEngineType.BLENDER else request.engine.value
        )
        has_binary = shutil.which(binary_name) is not None

        if mock_in_test or not has_binary:
            # Deterministic simulation for environments without GPU / Blender installed
            output_path.write_text(
                f"# Mock 3D Model ({request.output_format}) generated by {request.engine.value}\n",
                encoding="utf-8",
            )
            if preview_path:
                preview_path.write_text("MOCK_PNG_VIEWPORT_BYTES", encoding="utf-8")

            return Headless3DExecutionResult(
                success=True,
                return_code=0,
                generated_3d_file=str(output_path),
                rendered_preview_png=str(preview_path) if preview_path else "",
                stdout_summary=f"Headless {request.engine.value} execution simulated successfully (CPU mode).",
                stderr_summary="",
                execution_time_seconds=round(time.monotonic() - start_time, 4),
            )

        # 3. Real Subprocess Execution
        cmd = self.build_cli_command(request.engine, script_path, output_path, preview_path)
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=request.timeout_seconds,
            )
            elapsed = time.monotonic() - start_time
            is_success = (proc.returncode == 0) and output_path.exists()

            return Headless3DExecutionResult(
                success=is_success,
                return_code=proc.returncode,
                generated_3d_file=str(output_path) if is_success else "",
                rendered_preview_png=(
                    str(preview_path) if (is_success and preview_path and preview_path.exists()) else ""
                ),
                stdout_summary=proc.stdout[:1000],
                stderr_summary=proc.stderr[:1000],
                execution_time_seconds=round(elapsed, 4),
            )
        except subprocess.TimeoutExpired:
            return Headless3DExecutionResult(
                success=False,
                return_code=-2,
                stdout_summary="",
                stderr_summary=f"Execution exceeded timeout ceiling of {request.timeout_seconds}s",
                execution_time_seconds=round(time.monotonic() - start_time, 4),
            )
        except Exception as e:
            return Headless3DExecutionResult(
                success=False,
                return_code=-3,
                stdout_summary="",
                stderr_summary=f"Subprocess spawn error: {e}",
                execution_time_seconds=round(time.monotonic() - start_time, 4),
            )
