"""Config protection validator

Blocks agent modifications to existing linter/formatter configuration files.
LLMs tend to weaken lint rules to suppress errors instead of fixing the source code.
This validator enforces the principle: "fix the code, not the config."

[INPUT]
- (none — pure logic module)

[OUTPUT]
- ConfigProtectionValidator: Config protection validator

[POS]
Config protection validator
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

from ..core.operation_context import OperationType
from .base import Validator

if TYPE_CHECKING:
    from ..core.operation_context import OperationContext

PROTECTED_CONFIG_NAMES: frozenset[str] = frozenset(
    (
        # ESLint (legacy + flat config, all JS/TS/MJS/CJS variants)
        ".eslintrc",
        ".eslintrc.js",
        ".eslintrc.cjs",
        ".eslintrc.json",
        ".eslintrc.yml",
        ".eslintrc.yaml",
        "eslint.config.js",
        "eslint.config.mjs",
        "eslint.config.cjs",
        "eslint.config.ts",
        "eslint.config.mts",
        "eslint.config.cts",
        # Prettier
        ".prettierrc",
        ".prettierrc.js",
        ".prettierrc.cjs",
        ".prettierrc.json",
        ".prettierrc.yml",
        ".prettierrc.yaml",
        "prettier.config.js",
        "prettier.config.cjs",
        "prettier.config.mjs",
        # Biome
        "biome.json",
        "biome.jsonc",
        # Ruff (Python)
        ".ruff.toml",
        "ruff.toml",
        # TypeScript strict config
        "tsconfig.json",
        "tsconfig.build.json",
        # Stylelint
        ".stylelintrc",
        ".stylelintrc.json",
        ".stylelintrc.yml",
        # Markdownlint
        ".markdownlint.json",
        ".markdownlint.yaml",
        ".markdownlintrc",
        # Shell
        ".shellcheckrc",
        # Jest config (prevents disabling test expectations)
        "jest.config.js",
        "jest.config.ts",
        "jest.config.mjs",
        # Commitlint
        "commitlint.config.js",
        "commitlint.config.ts",
        "commitlint.config.cjs",
    )
)


class ConfigProtectionValidator(Validator):
    """Blocks modifications to existing linter/formatter config files.

    Allows first-time creation (project scaffolding) but blocks edits to
    existing configs, forcing the agent to fix source code instead.
    """

    async def _do_validate(self, context: OperationContext, path: str) -> None:
        if context.operation == OperationType.VIEW:
            return

        basename = Path(path).name
        if basename not in PROTECTED_CONFIG_NAMES:
            return

        if context.operation in (OperationType.CREATE, OperationType.STR_REPLACE):
            if os.path.exists(path):
                raise PermissionError(
                    f"BLOCKED: Modifying '{basename}' is not allowed.\n"
                    f"Fix the source code to satisfy linter/formatter rules "
                    f"instead of weakening the configuration.\n"
                    f"If you encounter lint errors, fix the actual code that "
                    f"violates the rules rather than disabling or relaxing them."
                )
