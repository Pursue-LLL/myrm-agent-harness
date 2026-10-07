"""Unit tests for PromptVariableContractSchemaValidator and pre-flight assertions.

[INPUT]
Template specifications, declared variable schemas, and valid/invalid runtime argument sets.

[OUTPUT]
Verification of pre-flight assertion errors, schema alignment reports,
deterministic rendering outcomes, and thread-safety gates.

[POS]
Quality gate for Item 121 in topic_06 roadmap.
"""

from concurrent.futures import ThreadPoolExecutor

import pytest

from myrm_agent_harness.runtime.context.prompt_variable_contract_types import (
    PromptVariableDefinition,
    PromptVariableMissingError,
    PromptVariableValidationError,
    VariableDataType,
)
from myrm_agent_harness.runtime.context.prompt_variable_contract_validator import (
    PromptVariableContractSchemaValidator,
)


def test_schema_inspection_and_binding() -> None:
    template = "Current workspace is {workspace_path} with max tokens {max_tokens}."
    variables = (
        PromptVariableDefinition(
            var_name="workspace_path",
            data_type=VariableDataType.PATH,
            required=True,
        ),
        PromptVariableDefinition(
            var_name="max_tokens",
            data_type=VariableDataType.INTEGER,
            required=True,
            default_value=8192,
        ),
    )
    validator = PromptVariableContractSchemaValidator(
        contract_name="test_contract",
        template=template,
        variables=variables,
    )
    report = validator.inspection_report
    assert report.is_fully_bound is True
    assert set(report.declared_variables) == {"workspace_path", "max_tokens"}
    assert set(report.template_placeholders) == {"workspace_path", "max_tokens"}
    assert len(report.missing_declarations) == 0
    assert len(report.unused_declarations) == 0


def test_strict_placeholder_alignment_rejection() -> None:
    template = "Hello {user_name}, your role is {role_title}."
    # role_title is missing in declared variables
    variables = (
        PromptVariableDefinition(
            var_name="user_name",
            data_type=VariableDataType.STRING,
            required=True,
        ),
    )
    with pytest.raises(PromptVariableValidationError) as exc:
        PromptVariableContractSchemaValidator(
            contract_name="broken_contract",
            template=template,
            variables=variables,
            strict_placeholder_alignment=True,
        )
    assert "undeclared placeholders in template" in str(exc.value)
    assert "role_title" in str(exc.value)


def test_successful_validation_and_deterministic_rendering() -> None:
    template = (
        "Project: {project_name}\n"
        "Root: {workspace_path}\n"
        "Workers: {worker_count}\n"
        "Debug: {is_debug}\n"
        "Tier: {tier_mode}"
    )
    variables = (
        PromptVariableDefinition(
            var_name="project_name",
            data_type=VariableDataType.STRING,
            required=True,
            regex_pattern=r"^[a-zA-Z0-9_\-]+$",
        ),
        PromptVariableDefinition(
            var_name="workspace_path",
            data_type=VariableDataType.PATH,
            required=True,
        ),
        PromptVariableDefinition(
            var_name="worker_count",
            data_type=VariableDataType.INTEGER,
            required=True,
        ),
        PromptVariableDefinition(
            var_name="is_debug",
            data_type=VariableDataType.BOOLEAN,
            required=False,
            default_value=False,
        ),
        PromptVariableDefinition(
            var_name="tier_mode",
            data_type=VariableDataType.ENUM,
            allowed_values=("standard", "turbo", "pro"),
            default_value="standard",
        ),
    )

    validator = PromptVariableContractSchemaValidator(
        contract_name="suite_contract",
        template=template,
        variables=variables,
    )

    params = {
        "project_name": "myrm_core",
        "workspace_path": "/var/tmp//project/subdir/..",  # Needs path normalization
        "worker_count": 16,
    }

    res1 = validator.validate_and_render(params)
    assert "Project: myrm_core" in res1.rendered_content
    assert "Root: /var/tmp/project" in res1.rendered_content
    assert "Workers: 16" in res1.rendered_content
    assert "Debug: false" in res1.rendered_content  # default value applied
    assert "Tier: standard" in res1.rendered_content  # default value applied
    assert len(res1.sha256_hash) == 64

    # Run again with same params -> SHA256 must be identical
    res2 = validator.validate_and_render(params)
    assert res1.sha256_hash == res2.sha256_hash


def test_missing_required_variable_rejection() -> None:
    template = "Active task: {task_id}"
    variables = (
        PromptVariableDefinition(
            var_name="task_id",
            data_type=VariableDataType.STRING,
            required=True,
        ),
    )
    validator = PromptVariableContractSchemaValidator(
        contract_name="task_contract",
        template=template,
        variables=variables,
    )

    with pytest.raises(PromptVariableMissingError) as exc1:
        validator.validate_and_render({})
    assert "Required prompt variable 'task_id' is missing" in str(exc1.value)

    with pytest.raises(PromptVariableMissingError) as exc2:
        validator.validate_and_render({"task_id": "   "})
    assert "cannot be empty" in str(exc2.value)


def test_type_and_enum_and_regex_violations() -> None:
    template = "Port: {port_num}, Mode: {mode}, Code: {code}"
    variables = (
        PromptVariableDefinition(
            var_name="port_num",
            data_type=VariableDataType.INTEGER,
            required=True,
        ),
        PromptVariableDefinition(
            var_name="mode",
            data_type=VariableDataType.ENUM,
            allowed_values=("read", "write"),
            required=True,
        ),
        PromptVariableDefinition(
            var_name="code",
            data_type=VariableDataType.STRING,
            regex_pattern=r"^[A-Z]{3}-\d{3}$",
            required=True,
        ),
    )
    validator = PromptVariableContractSchemaValidator(
        contract_name="strict_types",
        template=template,
        variables=variables,
    )

    # 1. Invalid integer
    with pytest.raises(PromptVariableValidationError) as exc1:
        validator.validate_and_render({"port_num": "not_a_number", "mode": "read", "code": "ABC-123"})
    assert "must be an integer" in str(exc1.value)

    # 2. Invalid enum
    with pytest.raises(PromptVariableValidationError) as exc2:
        validator.validate_and_render({"port_num": 8080, "mode": "execute", "code": "ABC-123"})
    assert "not in allowed enum options" in str(exc2.value)

    # 3. Invalid regex pattern
    with pytest.raises(PromptVariableValidationError) as exc3:
        validator.validate_and_render({"port_num": 8080, "mode": "read", "code": "invalid_code"})
    assert "does not match pattern" in str(exc3.value)


def test_excess_undeclared_variables_rejection() -> None:
    template = "Message: {msg}"
    variables = (
        PromptVariableDefinition(
            var_name="msg",
            data_type=VariableDataType.STRING,
            required=True,
        ),
    )
    validator = PromptVariableContractSchemaValidator(
        contract_name="excess_contract",
        template=template,
        variables=variables,
    )

    # Passing rogue variable not declared in contract
    with pytest.raises(PromptVariableValidationError) as exc:
        validator.validate_and_render({"msg": "hello", "rogue_extra_param": "jitter"})
    assert "received undeclared excess variables" in str(exc.value)


def test_thread_safety_concurrent_validation() -> None:
    template = "Thread worker: {worker_id}, count: {loop_cnt}"
    variables = (
        PromptVariableDefinition(
            var_name="worker_id",
            data_type=VariableDataType.STRING,
            required=True,
        ),
        PromptVariableDefinition(
            var_name="loop_cnt",
            data_type=VariableDataType.INTEGER,
            required=True,
        ),
    )
    validator = PromptVariableContractSchemaValidator(
        contract_name="threaded_contract",
        template=template,
        variables=variables,
    )

    def worker(worker_id: int) -> bool:
        res = validator.validate_and_render({
            "worker_id": f"worker_{worker_id}",
            "loop_cnt": worker_id * 10,
        })
        return len(res.sha256_hash) == 64 and f"worker_{worker_id}" in res.rendered_content

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(worker, i) for i in range(25)]
        results = [f.result() for f in futures]

    assert all(results)
