"""Tool, State, and Semantic Assertion Engine.

[INPUT]
- protocol::EvalCase (POS: eval case with expected tools and assertions)

[OUTPUT]
- ToolAssertion: assertion specification
- evaluate_tool_assertions(): tool evaluator
- evaluate_state_assertions(): state/output evaluator
- evaluate_sandbox_assertions(): sandbox evaluator
- evaluate_semantic_assertions(): LLM-as-a-judge semantic evaluator

[POS]
Provides pass/fail verification of agent tool calls, output text,
sandbox states, and subjective semantic evaluations via lightweight LLMs.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from myrm_agent_harness.eval.protocols import SandboxAssertion, SemanticAssertion, StateAssertion
    from myrm_agent_harness.toolkits.code_execution.executors.base import CodeExecutor


@dataclass(frozen=True, slots=True)
class ToolAssertion:
    """Specification for tool call assertions."""

    expected_tools: list[str | dict[str, Any]] = field(default_factory=list)
    require_all: bool = False


def evaluate_tool_assertions(
    tools_called: list[str | dict[str, Any]],
    assertion: ToolAssertion | None,
) -> tuple[bool | None, str | None]:
    """Evaluate tool assertions against actual tool calls.

    Returns (passed, details) where passed is None if no assertion provided.
    """
    if assertion is None or not assertion.expected_tools:
        return None, None

    def get_name(t: str | dict[str, Any] | Any) -> str:
        if isinstance(t, dict):
            return t.get("name", str(t))
        if hasattr(t, "name"):
            return t.name
        return str(t)

    expected = set(get_name(t) for t in assertion.expected_tools)
    called = set(get_name(t) for t in tools_called)

    if assertion.require_all:
        missing = expected - called
        if missing:
            return False, (f"Missing tools: {sorted(missing)}. Called: {sorted(called)}")
        return True, (f"All expected tools called: {sorted(expected)}. Called: {sorted(called)}")

    matched = expected & called
    if not matched:
        return False, (f"None of expected tools called. Expected one of: {sorted(expected)}. Called: {sorted(called)}")
    return True, (f"Expected tool(s) called: {sorted(matched)}. Called: {sorted(called)}")


async def evaluate_sandbox_assertions(
    assertions: list[SandboxAssertion],
    executor: CodeExecutor | None,
) -> tuple[bool | None, str | None]:
    """Evaluate sandbox state assertions.

    Args:
        assertions: List of SandboxAssertion objects.
        executor: CodeExecutor instance to interact with the sandbox.

    Returns:
        (passed, details) where passed is None if no assertions provided.
    """
    if not assertions:
        return None, None

    if not executor:
        return False, "CodeExecutor is required for sandbox assertions but was not provided."

    from myrm_agent_harness.toolkits.code_execution.executors.models import ExecutionContext

    for assertion in assertions:
        if assertion.type == "file_exists":
            exists = await executor.file_exists(assertion.target)
            if not exists:
                return False, f"Sandbox assertion failed: File {assertion.target} does not exist."
        elif assertion.type == "file_contains":
            exists = await executor.file_exists(assertion.target)
            if not exists:
                return False, f"Sandbox assertion failed: File {assertion.target} does not exist."
            content = await executor.read_file(assertion.target)
            if assertion.expected and assertion.expected not in content:
                return (
                    False,
                    f"Sandbox assertion failed: File {assertion.target} does not contain '{assertion.expected}'.",
                )
        elif assertion.type == "cmd_success":
            ctx = ExecutionContext(code=assertion.target)
            result = await executor.execute_bash(ctx)
            if not result.success:
                return (
                    False,
                    f"Sandbox assertion failed: Command '{assertion.target}' failed. Output: {result.stdout} {result.stderr}",
                )
        elif assertion.type == "file_not_exists":
            exists = await executor.file_exists(assertion.target)
            if exists:
                return False, f"Sandbox assertion failed: File {assertion.target} exists but should not."
        elif assertion.type == "cmd_output_contains":
            ctx = ExecutionContext(code=assertion.target)
            result = await executor.execute_bash(ctx)
            if not result.success:
                return (
                    False,
                    f"Sandbox assertion failed: Command '{assertion.target}' failed. Output: {result.stdout} {result.stderr}",
                )
            if assertion.expected and assertion.expected not in result.stdout:
                return (
                    False,
                    f"Sandbox assertion failed: Command '{assertion.target}' output does not contain '{assertion.expected}'. Output: {result.stdout}",
                )
        elif assertion.type == "json_matches":
            exists = await executor.file_exists(assertion.target)
            if not exists:
                return False, f"Sandbox assertion failed: File {assertion.target} does not exist."
            content = await executor.read_file(assertion.target)
            try:
                data = json.loads(content)
                if assertion.expected:
                    # Expected format: "key=value" or "key.subkey=value"
                    parts = assertion.expected.split("=", 1)
                    if len(parts) == 2:
                        key_path, expected_val = parts
                        keys = key_path.split(".")
                        current = data
                        for k in keys:
                            if isinstance(current, dict) and k in current:
                                current = current[k]
                            else:
                                return (
                                    False,
                                    f"Sandbox assertion failed: JSON key '{key_path}' not found in {assertion.target}.",
                                )
                        if str(current) != expected_val:
                            return (
                                False,
                                f"Sandbox assertion failed: JSON key '{key_path}' is '{current}', expected '{expected_val}'.",
                            )
                    else:
                        return (
                            False,
                            "Sandbox assertion failed: Invalid expected format for json_matches. Use 'key=value'.",
                        )
            except json.JSONDecodeError:
                return False, f"Sandbox assertion failed: File {assertion.target} is not valid JSON."
        else:
            return False, f"Sandbox assertion failed: Unknown assertion type '{assertion.type}'."

    return True, "All sandbox assertions passed."


def evaluate_state_assertions(
    assertions: list[StateAssertion],
    actual_output: str,
) -> tuple[bool | None, str | None]:
    """Evaluate state assertions against agent output.

    Args:
        assertions: List of StateAssertion objects.
        actual_output: The final answer or text output from the agent.

    Returns:
        (passed, details) where passed is None if no assertions provided.
    """
    if not assertions:
        return None, None

    for assertion in assertions:
        if assertion.type == "exact_match":
            if assertion.expected != actual_output:
                return (
                    False,
                    f"State assertion failed: expected exact match '{assertion.expected}', got '{actual_output}'",
                )
        elif assertion.type == "contains":
            if assertion.expected not in actual_output:
                return False, f"State assertion failed: expected output to contain '{assertion.expected}'"
        elif assertion.type == "not_contains":
            if assertion.expected in actual_output:
                return False, f"State assertion failed: output must NOT contain '{assertion.expected}'"
        elif assertion.type == "regex":
            if not re.search(assertion.expected, actual_output):
                return False, f"State assertion failed: output does not match regex '{assertion.expected}'"
        elif assertion.type == "json_valid":
            try:
                json.loads(actual_output)
            except (ValueError, TypeError):
                return False, "State assertion failed: output is not valid JSON"
        elif assertion.type == "json_schema":
            try:
                parsed = json.loads(actual_output)
            except (ValueError, TypeError):
                return False, "State assertion failed: output is not valid JSON (json_schema requires valid JSON)"
            try:
                schema = json.loads(assertion.expected)
            except (ValueError, TypeError):
                return False, f"State assertion failed: invalid JSON schema definition: '{assertion.expected}'"
            schema_error = _validate_json_schema(parsed, schema)
            if schema_error:
                return False, f"State assertion failed: JSON schema validation error: {schema_error}"
        elif assertion.type == "custom_python":
            safe_builtins = {
                "len": len,
                "str": str,
                "int": int,
                "float": float,
                "bool": bool,
                "list": list,
                "dict": dict,
                "set": set,
                "tuple": tuple,
                "isinstance": isinstance,
                "type": type,
                "any": any,
                "all": all,
                "sorted": sorted,
                "min": min,
                "max": max,
                "sum": sum,
                "abs": abs,
                "round": round,
                "enumerate": enumerate,
                "zip": zip,
                "map": map,
                "filter": filter,
                "range": range,
                "True": True,
                "False": False,
                "None": None,
            }
            try:
                result = eval(assertion.expected, {"__builtins__": safe_builtins}, {"output": actual_output})
                if not result:
                    return False, f"State assertion failed: custom expression '{assertion.expected}' evaluated to False"
            except Exception as exc:
                return False, f"State assertion failed: custom expression error: {exc}"
        elif assertion.type == "jaccard_similarity":
            set1 = set(assertion.expected.lower().split())
            set2 = set(actual_output.lower().split())
            intersection = len(set1.intersection(set2))
            union = len(set1.union(set2))
            similarity = intersection / union if union > 0 else 0.0
            if similarity < assertion.threshold:
                return (
                    False,
                    f"State assertion failed: Jaccard similarity {similarity:.2f} is below threshold {assertion.threshold:.2f}",
                )
        else:
            return False, f"State assertion failed: Unknown assertion type '{assertion.type}'"

    return True, "All state assertions passed."


def _validate_json_schema(data: object, schema: dict[str, object]) -> str | None:
    """Lightweight JSON schema validator supporting 'required' and 'properties.type' checks."""
    if not isinstance(schema, dict):
        return "Schema must be a JSON object"

    if "required" in schema:
        required_fields = schema["required"]
        if isinstance(required_fields, list) and isinstance(data, dict):
            for field_name in required_fields:
                if field_name not in data:
                    return f"Missing required field: '{field_name}'"

    if "properties" in schema and isinstance(schema["properties"], dict) and isinstance(data, dict):
        for prop_name, prop_schema in schema["properties"].items():
            if prop_name in data and isinstance(prop_schema, dict) and "type" in prop_schema:
                expected_type = prop_schema["type"]
                actual_value = data[prop_name]
                if not _check_json_type(actual_value, str(expected_type)):
                    return f"Field '{prop_name}' expected type '{expected_type}', got {type(actual_value).__name__}"

    return None


def _check_json_type(value: object, expected_type: str) -> bool:
    """Check if a value matches a JSON Schema type."""
    type_map: dict[str, tuple[type, ...]] = {
        "string": (str,),
        "number": (int, float),
        "integer": (int,),
        "boolean": (bool,),
        "array": (list,),
        "object": (dict,),
    }
    allowed_types = type_map.get(expected_type)
    if allowed_types is None:
        return True
    return isinstance(value, allowed_types)


async def evaluate_semantic_assertions(
    assertions: list[SemanticAssertion],
    actual_output: str,
) -> tuple[bool | None, str | None]:
    """Evaluate semantic assertions using an LLM as a judge.

    Args:
        assertions: List of SemanticAssertion objects.
        actual_output: The final answer or text output from the agent.

    Returns:
        (passed, details) where passed is None if no assertions provided.
    """
    if not assertions:
        return None, None

    try:
        from litellm import acompletion
    except ImportError:
        return False, "Semantic assertions require the 'litellm' package to be installed."

    default_judge_model = os.environ.get("MYRM_EVAL_JUDGE_MODEL", "gpt-4o-mini")
    default_binary_prompt = (
        "You are an expert evaluator. Evaluate if the ACTUAL_OUTPUT meets the CRITERIA.\n"
        "CRITERIA: {criteria}\n"
        "ACTUAL_OUTPUT: {output}\n\n"
        "Reply EXACTLY with 'PASS' if it meets the criteria, or 'FAIL: <reason>' if it does not."
    )
    default_scoring_prompt = (
        "You are an expert evaluator. Score how well the ACTUAL_OUTPUT meets the CRITERIA.\n"
        "CRITERIA: {criteria}\n"
        "ACTUAL_OUTPUT: {output}\n\n"
        "Reply with ONLY a decimal number between 0.0 and 1.0 (e.g. 0.75). "
        "1.0 means perfectly meets criteria, 0.0 means completely fails."
    )

    for assertion in assertions:
        if assertion.type == "llm_judge":
            model = assertion.judge_model or default_judge_model
            use_scoring = assertion.threshold < 1.0

            if assertion.judge_prompt:
                template = assertion.judge_prompt
            elif use_scoring:
                template = default_scoring_prompt
            else:
                template = default_binary_prompt

            prompt = template.format(criteria=assertion.expected, output=actual_output)
            try:
                response = await acompletion(
                    model=model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.0,
                    num_retries=2,
                )
                raw_content = response.choices[0].message.content
                if not raw_content:
                    return False, "Semantic assertion: judge returned empty response"
                result_text = raw_content.strip()

                if use_scoring:
                    try:
                        score = float(result_text.split()[0])
                        score = max(0.0, min(1.0, score))
                    except (ValueError, IndexError):
                        if result_text.startswith("PASS"):
                            score = 1.0
                        elif result_text.startswith("FAIL"):
                            score = 0.0
                        else:
                            return False, f"Semantic assertion: judge returned unparseable score '{result_text}'"

                    if score >= assertion.threshold:
                        continue
                    else:
                        return (
                            False,
                            f"Semantic assertion failed: score {score:.2f} < threshold {assertion.threshold:.2f}",
                        )
                else:
                    if result_text.startswith("PASS"):
                        continue
                    else:
                        return False, f"Semantic assertion failed: {result_text}"
            except Exception as e:
                return False, f"Semantic assertion failed due to LLM error: {e!s}"
        else:
            return False, f"Semantic assertion failed: Unknown assertion type '{assertion.type}'"

    return True, "All semantic assertions passed."
