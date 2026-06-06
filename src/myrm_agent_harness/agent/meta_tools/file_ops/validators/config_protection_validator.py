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

PROTECTED_LOCKFILE_NAMES: frozenset[str] = frozenset(
    (
        "package-lock.json",
        "yarn.lock",
        "pnpm-lock.yaml",
        "bun.lockb",
        "uv.lock",
        "poetry.lock",
        "Pipfile.lock",
        "go.sum",
        "Cargo.lock",
        "Gemfile.lock",
        "composer.lock",
    )
)


class ConfigProtectionValidator(Validator):
    """Blocks modifications to existing linter/formatter config files and lockfiles.

    Allows first-time creation (project scaffolding) but blocks edits to
    existing configs/lockfiles, forcing the agent to fix source code or use package managers.
    """

    async def _do_validate(self, context: OperationContext, path: str) -> None:
        if context.operation == OperationType.VIEW:
            return

        basename = Path(path).name
        is_config = basename in PROTECTED_CONFIG_NAMES
        is_lockfile = basename in PROTECTED_LOCKFILE_NAMES

        if not (is_config or is_lockfile):
            return

        if context.operation in (OperationType.CREATE, OperationType.STR_REPLACE):
            if os.path.exists(path):
                if is_lockfile:
                    raise PermissionError(
                        f"BLOCKED: 严禁手动修改锁文件 '{basename}'。\n"
                        f"请使用合法的包管理器命令（如 uv sync, npm install, pnpm install）来解决依赖，\n"
                        f"绝对不要尝试通过字符串替换或直接编辑来解决版本冲突！"
                    )
                else:
                    raise PermissionError(
                        f"BLOCKED: Modifying '{basename}' is not allowed.\n"
                        f"Fix the source code to satisfy linter/formatter rules "
                        f"instead of weakening the configuration.\n"
                        f"If you encounter lint errors, fix the actual code that "
                        f"violates the rules rather than disabling or relaxing them."
                    )
