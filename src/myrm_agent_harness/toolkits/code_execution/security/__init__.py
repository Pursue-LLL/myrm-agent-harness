"""Execution security — shell command analysis, blacklists, and validators.

- shell_command_analyzer.py: shell command threat detection (injection, dangerous patterns)
- risk_classifier.py: command risk classification (SAFE/UNKNOWN) with flag-level validation
- safe_command_configs.py: subcommand flag whitelist data (git read-only subcommands)
- blacklist.py: Python module blacklists, env var blacklists, file-modifying commands
- validator.py: unified validation interface + env var sanitization (ALL/CORE/NONE policies)
- shell_bleed.py: script env var leak detection (warning-only)
- archive_sanitizer.py: archive command sanitization
"""

from myrm_agent_harness.toolkits.code_execution.security.archive_sanitizer import (
    sanitize_archive_command,
)
from myrm_agent_harness.toolkits.code_execution.security.blacklist import (
    CORE_DANGEROUS_MODULES,
    CORE_SAFE_ENV_VARS,
    DANGEROUS_ENV_PREFIXES,
    DANGEROUS_ENV_VARS,
    DANGEROUS_ENV_WILDCARDS,
    DANGEROUS_MODULES,
    DANGEROUS_MODULES_REASONS,
    FILE_MODIFYING_COMMANDS,
    NETWORK_MODULES,
    get_dangerous_modules,
)
from myrm_agent_harness.toolkits.code_execution.security.risk_classifier import (
    SAFE_COMMANDS,
    CommandRiskLevel,
    classify_command_risk,
)
from myrm_agent_harness.toolkits.code_execution.security.safe_command_configs import (
    GIT_SAFE_SUBCOMMANDS,
    SUBCOMMAND_CONFIGS,
    FlagArgType,
    SubcommandConfig,
)
from myrm_agent_harness.toolkits.code_execution.security.shell_command_analyzer import (
    CommandThreat,
    ThreatLevel,
    analyze_command,
    has_block_threat,
    has_escalate_threat,
    is_integration_mutation_command,
    register_integration_write_patterns,
)
from myrm_agent_harness.toolkits.code_execution.security.validator import (
    EnvInheritPolicy,
    ValidationResult,
    is_command_allowed,
    is_module_allowed,
    is_path_allowed,
    is_path_component_safe,
    sanitize_env,
    validate_command,
    validate_module,
    validate_path,
    validate_path_component,
)

__all__ = [
    "CORE_DANGEROUS_MODULES",
    "CORE_SAFE_ENV_VARS",
    "DANGEROUS_ENV_PREFIXES",
    "DANGEROUS_ENV_VARS",
    "DANGEROUS_ENV_WILDCARDS",
    # Blacklist definitions
    "DANGEROUS_MODULES",
    "DANGEROUS_MODULES_REASONS",
    "FILE_MODIFYING_COMMANDS",
    "GIT_SAFE_SUBCOMMANDS",
    "NETWORK_MODULES",
    "SAFE_COMMANDS",
    "SUBCOMMAND_CONFIGS",
    # Command risk classification
    "CommandRiskLevel",
    "CommandThreat",
    # Env sanitization
    "EnvInheritPolicy",
    # Subcommand flag configs
    "FlagArgType",
    "SubcommandConfig",
    # Shell command analysis
    "ThreatLevel",
    # Validation
    "ValidationResult",
    "analyze_command",
    "classify_command_risk",
    # Dynamic blacklist
    "get_dangerous_modules",
    "has_block_threat",
    "has_escalate_threat",
    "is_integration_mutation_command",
    "is_command_allowed",
    # Simplified interfaces
    "is_module_allowed",
    "is_path_allowed",
    "is_path_component_safe",
    # Archive sanitization
    "sanitize_archive_command",
    "sanitize_env",
    "validate_command",
    "validate_module",
    "validate_path",
    "validate_path_component",
]
