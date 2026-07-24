"""LangGraph ToolNode monkey-patch for robust tool_call args handling.

Applied once at module load time by ``base_agent``.  Protections:

1. **Null-args recovery** — LangGraph internally mutates ``tool_call["args"]``
   to ``None`` between ``_arun_one`` / ``_run_one`` and ``_inject_tool_args``.
   We stash a deep-copy at entry and restore if nullified.

2. **Stringified-JSON coercion** — Some LLMs send list/dict parameters as JSON
   strings instead of native types.  We detect such fields via the tool's JSON
   Schema and parse them before Pydantic validation.

3. **Dynamic tools** — We do not reject tool names missing from ``ToolNode.tools_by_name``
   before ``awrap_tool_call`` runs; middleware may attach a ``BaseTool`` via
   ``ToolCallRequest.override(tool=...)`` (e.g. dynamic tools from skill middleware).

4. **Stage-level mixed concurrency** — Tool batches are planned into ordered stages:
   each stage runs only mutually safe calls in parallel, while unsafe/conflicting calls
   are isolated into singleton stages. This preserves failure short-circuit semantics
   without forcing full-batch serialization.

[INPUT]
- (none)

[OUTPUT]
- apply_langgraph_tool_args_guard: Apply the ToolNode monkey-patch (idempotent).

[POS]
LangGraph ToolNode monkey-patch for robust tool_call args handling.
"""

from __future__ import annotations

from myrm_agent_harness.utils.logger_utils import get_agent_logger

logger = get_agent_logger(__name__)

_TOOL_ARGS_GUARD_APPLIED = False


def apply_langgraph_tool_args_guard() -> None:
    """Apply the ToolNode monkey-patch (idempotent)."""
    global _TOOL_ARGS_GUARD_APPLIED
    if _TOOL_ARGS_GUARD_APPLIED:
        return
    _TOOL_ARGS_GUARD_APPLIED = True

    import json as _json
    from copy import deepcopy

    from langgraph.prebuilt.tool_node import ToolNode

    _args_stash: dict[str, dict[str, object]] = {}
    _schema_coerce_cache: dict[str, frozenset[str]] = {}

    def _stash_args(call: dict[str, object]) -> None:
        tc_id = call.get("id", "")
        args = call.get("args")
        if args is not None and isinstance(tc_id, str):
            _args_stash[tc_id] = deepcopy(args)

    def _get_coercible_fields(tool: object) -> frozenset[str]:
        """Return field names whose schema type is array or object."""
        schema_cls = getattr(tool, "args_schema", None)
        if schema_cls is None:
            return frozenset()
        cls_name = getattr(schema_cls, "__name__", id(schema_cls))
        cached = _schema_coerce_cache.get(str(cls_name))
        if cached is not None:
            return cached

        try:
            schema = schema_cls.model_json_schema()
        except Exception:
            _schema_coerce_cache[str(cls_name)] = frozenset()
            return frozenset()

        fields: set[str] = set()
        for name, prop in schema.get("properties", {}).items():
            prop_type = prop.get("type")
            if prop_type in ("array", "object"):
                fields.add(name)
                continue
            for variant in prop.get("anyOf", []):
                if variant.get("type") in ("array", "object"):
                    fields.add(name)
                    break

        result = frozenset(fields)
        _schema_coerce_cache[str(cls_name)] = result
        return result

    def _coerce_stringified_json(
        args: dict[str, object],
        coercible: frozenset[str],
    ) -> None:
        """Parse JSON strings in-place for fields that expect array/object."""
        for key in coercible:
            value = args.get(key)
            if not isinstance(value, str) or len(value) < 2:
                continue
            if value[0] not in ("[", "{"):
                continue
            try:
                parsed = _json.loads(value)
                if isinstance(parsed, (list, dict)):
                    args[key] = parsed
                    logger.info("Coerced stringified JSON for arg '%s'", key)
            except (ValueError, _json.JSONDecodeError):
                pass

    _orig_arun = ToolNode._arun_one

    async def _arun_one_with_guard(self, call, input_type, tool_runtime):  # type: ignore[no-untyped-def]
        _stash_args(call)
        # Do not block unknown tool names here: ToolNode + awrap_tool_call may supply a
        # BaseTool via ToolCallRequest.override(tool=...) (e.g. dynamic skill tools).
        return await _orig_arun(self, call, input_type, tool_runtime)

    ToolNode._arun_one = _arun_one_with_guard  # type: ignore[method-assign]

    _orig_run_one = ToolNode._run_one

    def _run_one_with_guard(self, call, input_type, tool_runtime):  # type: ignore[no-untyped-def]
        _stash_args(call)
        return _orig_run_one(self, call, input_type, tool_runtime)

    ToolNode._run_one = _run_one_with_guard  # type: ignore[method-assign]

    _orig_inject = getattr(ToolNode, "_inject_tool_args", None)
    if _orig_inject:

        def _safe_inject(self, tool_call, tool_runtime, tool=None):  # type: ignore[no-untyped-def]
            tc_id = tool_call.get("id", "")
            if tool_call.get("args") is None:
                stashed = _args_stash.pop(tc_id, None)
                if stashed is not None:
                    tool_call["args"] = stashed
                    logger.info(
                        "Recovered tool_call args from stash for %s",
                        tool_call.get("name"),
                    )
                else:
                    tool_call["args"] = {}
                    logger.warning(
                        "Tool call args None for %s and no stash available",
                        tool_call.get("name"),
                    )
            else:
                _args_stash.pop(tc_id, None)

            args = tool_call.get("args")
            if tool is not None and isinstance(args, dict):
                coercible = _get_coercible_fields(tool)
                if coercible:
                    _coerce_stringified_json(args, coercible)

            return _orig_inject(self, tool_call, tool_runtime, tool)

        ToolNode._inject_tool_args = _safe_inject  # type: ignore[method-assign]

    def _tool_output_failed(out: object) -> bool:
        if hasattr(out, "status") and getattr(out, "status") == "error":
            return True
        if isinstance(out, list):
            return any(getattr(m, "status", None) == "error" for m in out)
        return False

    def _append_abort_messages(
        outputs: list[object],
        tool_calls: list[dict[str, object]],
        executed_mask: list[bool],
    ) -> None:
        from langchain_core.messages import ToolMessage

        for idx, rem_call in enumerate(tool_calls):
            if executed_mask[idx]:
                continue
            outputs.append(
                ToolMessage(
                    content="Aborted: A previous tool call in this batch failed. Mid-batch short-circuit applied.",
                    name=rem_call.get("name", "unknown"),
                    tool_call_id=rem_call.get("id", ""),
                    status="error",
                )
            )

    _orig_afunc = getattr(ToolNode, "_afunc", None)

    if _orig_afunc:

        async def _afunc_with_guard(self, input, config, runtime):  # type: ignore[no-untyped-def]
            import asyncio

            from langchain_core.runnables.config import get_config_list
            from langgraph.prebuilt.tool_node import ToolRuntime

            tool_calls, input_type = self._parse_input(input)
            config_list = get_config_list(config, len(tool_calls))

            tool_runtimes = []
            for call, cfg in zip(tool_calls, config_list, strict=False):
                state = self._extract_state(input, cfg)
                tool_runtime = ToolRuntime(
                    state=state,
                    tool_call_id=call["id"],
                    config=cfg,
                    context=runtime.context,
                    store=runtime.store,
                    stream_writer=runtime.stream_writer,
                    tools=list(self.tools_by_name.values()),
                    execution_info=runtime.execution_info,
                    server_info=runtime.server_info,
                )
                tool_runtimes.append(tool_runtime)

            from myrm_agent_harness.agent.middlewares.concurrency_router import (
                build_tool_execution_stages,
            )

            stage_plan = build_tool_execution_stages(tool_calls)
            outputs: list[object] = []
            executed_mask = [False] * len(tool_calls)

            for stage in stage_plan:
                if len(stage) > 1:
                    for idx in stage:
                        tool_calls[idx]["__smart_concurrent_safe__"] = True
                    coros = [
                        self._arun_one(tool_calls[idx], input_type, tool_runtimes[idx])
                        for idx in stage
                    ]
                    stage_outputs = await asyncio.gather(*coros)
                    for idx, out in zip(stage, stage_outputs, strict=False):
                        executed_mask[idx] = True
                        outputs.append(out)

                    failed_idx = next(
                        (
                            idx
                            for idx, out in zip(stage, stage_outputs, strict=False)
                            if _tool_output_failed(out)
                        ),
                        None,
                    )
                    if failed_idx is not None:
                        logger.warning(
                            "Mid-batch action failed (%s). Preserving partial results and aborting remainder.",
                            tool_calls[failed_idx].get("name", ""),
                        )
                        _append_abort_messages(outputs, tool_calls, executed_mask)
                        break
                    continue

                idx = stage[0]
                out = await self._arun_one(
                    tool_calls[idx], input_type, tool_runtimes[idx]
                )
                executed_mask[idx] = True
                outputs.append(out)

                if _tool_output_failed(out):
                    logger.warning(
                        "Mid-batch action failed (%s). Preserving partial results and aborting remainder.",
                        tool_calls[idx].get("name", ""),
                    )
                    _append_abort_messages(outputs, tool_calls, executed_mask)
                    break

            return self._combine_tool_outputs(outputs, input_type)

        ToolNode._afunc = _afunc_with_guard  # type: ignore[method-assign]

    _orig_func = getattr(ToolNode, "_func", None)

    if _orig_func:

        def _func_with_guard(self, input, config, runtime):  # type: ignore[no-untyped-def]
            from langchain_core.runnables.config import get_config_list
            from langgraph.prebuilt.tool_node import ToolRuntime

            tool_calls, input_type = self._parse_input(input)
            config_list = get_config_list(config, len(tool_calls))

            tool_runtimes = []
            for call, cfg in zip(tool_calls, config_list, strict=False):
                state = self._extract_state(input, cfg)
                tool_runtime = ToolRuntime(
                    state=state,
                    tool_call_id=call["id"],
                    config=cfg,
                    context=runtime.context,
                    store=runtime.store,
                    stream_writer=runtime.stream_writer,
                    tools=list(self.tools_by_name.values()),
                    execution_info=runtime.execution_info,
                    server_info=runtime.server_info,
                )
                tool_runtimes.append(tool_runtime)

            from myrm_agent_harness.agent.middlewares.concurrency_router import (
                build_tool_execution_stages,
            )

            stage_plan = build_tool_execution_stages(tool_calls)
            outputs: list[object] = []
            executed_mask = [False] * len(tool_calls)

            for stage in stage_plan:
                if len(stage) > 1:
                    for idx in stage:
                        tool_calls[idx]["__smart_concurrent_safe__"] = True
                    from langchain_core.runnables.config import get_executor_for_config

                    with get_executor_for_config(config) as executor:
                        stage_calls = [tool_calls[idx] for idx in stage]
                        stage_input_types = [input_type] * len(stage_calls)
                        stage_runtimes = [tool_runtimes[idx] for idx in stage]
                        stage_outputs = list(
                            executor.map(
                                self._run_one,
                                stage_calls,
                                stage_input_types,
                                stage_runtimes,
                            )
                        )
                    for idx, out in zip(stage, stage_outputs, strict=False):
                        executed_mask[idx] = True
                        outputs.append(out)

                    failed_idx = next(
                        (
                            idx
                            for idx, out in zip(stage, stage_outputs, strict=False)
                            if _tool_output_failed(out)
                        ),
                        None,
                    )
                    if failed_idx is not None:
                        logger.warning(
                            "Mid-batch action failed (%s). Preserving partial results and aborting remainder.",
                            tool_calls[failed_idx].get("name", ""),
                        )
                        _append_abort_messages(outputs, tool_calls, executed_mask)
                        break
                    continue

                idx = stage[0]
                out = self._run_one(tool_calls[idx], input_type, tool_runtimes[idx])
                executed_mask[idx] = True
                outputs.append(out)

                if _tool_output_failed(out):
                    logger.warning(
                        "Mid-batch action failed (%s). Preserving partial results and aborting remainder.",
                        tool_calls[idx].get("name", ""),
                    )
                    _append_abort_messages(outputs, tool_calls, executed_mask)
                    break

            return self._combine_tool_outputs(outputs, input_type)

        ToolNode._func = _func_with_guard  # type: ignore[method-assign]
