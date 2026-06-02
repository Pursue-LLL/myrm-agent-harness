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
   ``ToolCallRequest.override(tool=...)`` (e.g. deferred tools after ``discover_capability``).

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
        args: dict[str, object], coercible: frozenset[str],
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
        # BaseTool via ToolCallRequest.override(tool=...) (e.g. deferred tools after
        # discover_capability). Validation runs in _execute_tool_async when tool stays None.
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
                    logger.info("Recovered tool_call args from stash for %s", tool_call.get("name"))
                else:
                    tool_call["args"] = {}
                    logger.warning("Tool call args None for %s and no stash available", tool_call.get("name"))
            else:
                _args_stash.pop(tc_id, None)

            args = tool_call.get("args")
            if tool is not None and isinstance(args, dict):
                coercible = _get_coercible_fields(tool)
                if coercible:
                    _coerce_stringified_json(args, coercible)

            return _orig_inject(self, tool_call, tool_runtime, tool)

        ToolNode._inject_tool_args = _safe_inject  # type: ignore[method-assign]

    _orig_afunc = getattr(ToolNode, "_afunc", None)

    if _orig_afunc:
        async def _afunc_with_guard(self, input, config, runtime):  # type: ignore[no-untyped-def]
            import asyncio

            from langchain_core.messages import ToolMessage
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

            from myrm_agent_harness.agent.middlewares.concurrency_router import should_parallelize_tool_batch

            is_smart_parallel = should_parallelize_tool_batch(tool_calls)
            has_unsafe = not is_smart_parallel

            outputs = []
            if not has_unsafe:
                for call in tool_calls:
                    call["__smart_concurrent_safe__"] = True
                coros = [self._arun_one(call, input_type, tr) for call, tr in zip(tool_calls, tool_runtimes, strict=False)]
                outputs = await asyncio.gather(*coros)
            else:
                for call, tr in zip(tool_calls, tool_runtimes, strict=False):
                    out = await self._arun_one(call, input_type, tr)
                    outputs.append(out)

                    failed = False
                    if (hasattr(out, "status") and out.status == "error") or (isinstance(out, list) and any(getattr(m, "status", None) == "error" for m in out)):
                        failed = True

                    if failed:
                        logger.warning(
                            "Mid-batch action failed (%s). Preserving partial results and aborting remainder.",
                            call.get("name", "")
                        )
                        for rem_call in tool_calls[len(outputs):]:
                            outputs.append(
                                ToolMessage(
                                    content="Aborted: A previous tool call in this batch failed. Mid-batch short-circuit applied.",
                                    name=rem_call.get("name", "unknown"),
                                    tool_call_id=rem_call.get("id", ""),
                                    status="error"
                                )
                            )
                        break

            return self._combine_tool_outputs(outputs, input_type)

        ToolNode._afunc = _afunc_with_guard  # type: ignore[method-assign]

    _orig_func = getattr(ToolNode, "_func", None)

    if _orig_func:
        def _func_with_guard(self, input, config, runtime):  # type: ignore[no-untyped-def]
            from langchain_core.messages import ToolMessage
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

            from myrm_agent_harness.agent.middlewares.concurrency_router import should_parallelize_tool_batch

            is_smart_parallel = should_parallelize_tool_batch(tool_calls)
            has_unsafe = not is_smart_parallel

            outputs = []
            if not has_unsafe:
                for call in tool_calls:
                    call["__smart_concurrent_safe__"] = True
                from langchain_core.runnables.config import get_executor_for_config
                with get_executor_for_config(config) as executor:
                    input_types = [input_type] * len(tool_calls)
                    outputs = list(executor.map(self._run_one, tool_calls, input_types, tool_runtimes))
            else:
                for call, tr in zip(tool_calls, tool_runtimes, strict=False):
                    out = self._run_one(call, input_type, tr)
                    outputs.append(out)

                    failed = False
                    if (hasattr(out, "status") and out.status == "error") or (isinstance(out, list) and any(getattr(m, "status", None) == "error" for m in out)):
                        failed = True

                    if failed:
                        logger.warning(
                            "Mid-batch action failed (%s). Preserving partial results and aborting remainder.",
                            call.get("name", "")
                        )
                        for rem_call in tool_calls[len(outputs):]:
                            outputs.append(
                                ToolMessage(
                                    content="Aborted: A previous tool call in this batch failed. Mid-batch short-circuit applied.",
                                    name=rem_call.get("name", "unknown"),
                                    tool_call_id=rem_call.get("id", ""),
                                    status="error"
                                )
                            )
                        break

            return self._combine_tool_outputs(outputs, input_type)

        ToolNode._func = _func_with_guard  # type: ignore[method-assign]
