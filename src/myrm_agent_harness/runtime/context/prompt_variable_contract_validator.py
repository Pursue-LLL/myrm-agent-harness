"""Prompt variable contract validator and pre-flight schema assertion engine.

[INPUT]
Template variable declarations, prompt templates, and runtime parameter maps.

[OUTPUT]
Validated and rendered deterministic prompt strings, pre-flight assertion reports,
and SHA-256 stable fingerprints for KV cache preservation.

[POS]
Item 121 in topic_06 roadmap: pre-flight assertion against variable-induced prefix cache jitter.
"""

import hashlib
import os
import re
import threading
import time
from collections.abc import Mapping, Sequence

from myrm_agent_harness.runtime.context.prompt_variable_contract_types import (
    PromptContractSchemaInspectionReport,
    PromptTemplateRenderResult,
    PromptVariableDefinition,
    PromptVariableMissingError,
    PromptVariableValidationError,
    VariableDataType,
)

_PLACEHOLDER_REGEX = re.compile(r"\{([a-zA-Z0-9_]+)\}")


class PromptVariableContractSchemaValidator:
    """Pre-flight assertion validator and renderer for prompt template variables."""

    def __init__(
        self,
        contract_name: str,
        template: str,
        variables: Sequence[PromptVariableDefinition],
        strict_placeholder_alignment: bool = True,
    ) -> None:
        self.contract_name = contract_name
        self.template = template
        self._lock = threading.RLock()
        self._variables: dict[str, PromptVariableDefinition] = {v.var_name: v for v in variables}

        # Analyze template placeholders
        found_placeholders = tuple(dict.fromkeys(_PLACEHOLDER_REGEX.findall(template)))
        declared_names = tuple(self._variables.keys())

        missing_decl = tuple(p for p in found_placeholders if p not in self._variables)
        unused_decl = tuple(d for d in declared_names if d not in found_placeholders)

        self._inspection_report = PromptContractSchemaInspectionReport(
            contract_name=contract_name,
            is_fully_bound=(len(missing_decl) == 0 and len(unused_decl) == 0),
            declared_variables=declared_names,
            template_placeholders=found_placeholders,
            missing_declarations=missing_decl,
            unused_declarations=unused_decl,
        )

        if strict_placeholder_alignment and missing_decl:
            raise PromptVariableValidationError(
                f"Contract '{contract_name}' has undeclared placeholders in template: {missing_decl}"
            )

    @property
    def inspection_report(self) -> PromptContractSchemaInspectionReport:
        """Inspection report comparing template placeholders with declared contracts."""
        return self._inspection_report

    def validate_and_render(
        self, params: Mapping[str, str | int | bool]
    ) -> PromptTemplateRenderResult:
        """Validate input parameters and render deterministic prompt string."""
        start_time = time.perf_counter()
        with self._lock:
            # 1. Reject unknown excess parameters to prevent untracked cache jitter
            declared_set = set(self._variables.keys())
            input_set = set(params.keys())
            excess_keys = input_set - declared_set
            if excess_keys:
                raise PromptVariableValidationError(
                    f"Contract '{self.contract_name}' received undeclared excess variables: {sorted(excess_keys)}"
                )

            rendered_dict: dict[str, str] = {}

            # 2. Check each declared variable
            for var_name, var_def in self._variables.items():
                raw_val = params.get(var_name)

                # Missing value handling
                if raw_val is None:
                    if var_def.default_value is not None:
                        raw_val = var_def.default_value
                    elif var_def.required:
                        raise PromptVariableMissingError(
                            f"Required prompt variable '{var_name}' is missing in contract '{self.contract_name}'"
                        )
                    else:
                        rendered_dict[var_name] = ""
                        continue

                # Type-specific validation and normalization
                if var_def.data_type == VariableDataType.STRING:
                    str_val = str(raw_val).strip()
                    if var_def.required and not str_val:
                        raise PromptVariableMissingError(
                            f"Required string variable '{var_name}' cannot be empty"
                        )
                    rendered_dict[var_name] = str_val

                elif var_def.data_type == VariableDataType.INTEGER:
                    try:
                        int_val = int(raw_val)
                    except (ValueError, TypeError) as err:
                        raise PromptVariableValidationError(
                            f"Variable '{var_name}' must be an integer, got: {raw_val}"
                        ) from err
                    rendered_dict[var_name] = str(int_val)

                elif var_def.data_type == VariableDataType.BOOLEAN:
                    if not isinstance(raw_val, bool):
                        raise PromptVariableValidationError(
                            f"Variable '{var_name}' must be a boolean, got: {raw_val}"
                        )
                    rendered_dict[var_name] = "true" if raw_val else "false"

                elif var_def.data_type == VariableDataType.PATH:
                    path_str = str(raw_val).strip()
                    if not path_str:
                        raise PromptVariableValidationError(
                            f"Path variable '{var_name}' cannot be empty"
                        )
                    # Normalize path deterministically
                    norm_path = os.path.normpath(path_str)
                    rendered_dict[var_name] = norm_path

                elif var_def.data_type == VariableDataType.ENUM:
                    str_enum = str(raw_val)
                    if var_def.allowed_values and str_enum not in var_def.allowed_values:
                        raise PromptVariableValidationError(
                            f"Variable '{var_name}' value '{str_enum}' not in allowed enum options: "
                            f"{var_def.allowed_values}"
                        )
                    rendered_dict[var_name] = str_enum

                # Check regex pattern if specified
                if var_def.regex_pattern is not None:
                    pattern = re.compile(var_def.regex_pattern)
                    if not pattern.fullmatch(rendered_dict[var_name]):
                        raise PromptVariableValidationError(
                            f"Variable '{var_name}' value '{rendered_dict[var_name]}' does not match pattern '{var_def.regex_pattern}'"
                        )

            # 3. Deterministic template substitution
            def replacer(match: re.Match[str]) -> str:
                key = match.group(1)
                return rendered_dict.get(key, "")

            rendered_text = _PLACEHOLDER_REGEX.sub(replacer, self.template)
            sha256_hash = hashlib.sha256(rendered_text.encode("utf-8")).hexdigest()
            duration_ms = (time.perf_counter() - start_time) * 1000.0

            return PromptTemplateRenderResult(
                rendered_content=rendered_text,
                variables_applied=rendered_dict,
                sha256_hash=sha256_hash,
                render_duration_ms=duration_ms,
            )
