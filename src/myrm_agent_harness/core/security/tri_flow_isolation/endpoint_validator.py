"""Zero-Guesswork Endpoint Validator to block hallucinations and blind API probes."""

from __future__ import annotations

import re

from .types import DocumentedEndpointSpec, EndpointValidationResult


class EndpointValidator:
    """Enforces zero-guesswork strict whitelist on outgoing HTTP, RPC, and smart contract calls.

    Blocks any blind probes or guessed endpoints injected through adversarial prompts.
    """

    def __init__(self, enforce_strict: bool = True) -> None:
        self._endpoints: dict[str, list[DocumentedEndpointSpec]] = {}
        self._enforce_strict: bool = enforce_strict

    def register_endpoint(self, spec: DocumentedEndpointSpec) -> None:
        """Register documented endpoint specification for a service."""
        service_key = spec.service.strip().lower()
        if service_key not in self._endpoints:
            self._endpoints[service_key] = []
        self._endpoints[service_key].append(spec)

    def _match_path(self, spec_path: str, request_path: str) -> bool:
        """Match request path against documented path template (e.g. /orders/{id})."""
        clean_spec = spec_path.strip().rstrip("/") or "/"
        clean_req = request_path.strip().rstrip("/") or "/"

        if clean_spec == clean_req:
            return True

        # Convert simple parameter templates like {id} to regex [^/]+
        pattern = re.sub(r"\{[a-zA-Z0-9_]+\}", r"[^/]+", clean_spec)
        regex = f"^{pattern}$"
        return bool(re.match(regex, clean_req))

    def validate_endpoint_call(
        self,
        service: str,
        path: str,
        method: str = "GET",
        function_name: str | None = None,
    ) -> EndpointValidationResult:
        """Inspect if the outgoing destination path and method are explicitly documented.

        Returns:
            EndpointValidationResult with approval status and defense rationale.
        """
        service_key = service.strip().lower()
        req_method = method.strip().upper()
        clean_path = path.strip()

        specs = self._endpoints.get(service_key)
        if not specs:
            if self._enforce_strict:
                return EndpointValidationResult(
                    is_allowed=False,
                    service=service,
                    endpoint=path,
                    method=method,
                    reason=(
                        f"Zero-Guesswork violation: service '{service}' has no documented endpoints "
                        "registered; blind invocation strictly blocked."
                    ),
                )
            return EndpointValidationResult(
                is_allowed=True,
                service=service,
                endpoint=path,
                method=method,
                reason=f"Service '{service}' permitted in permissive mode.",
            )

        matched_spec: DocumentedEndpointSpec | None = None
        for spec in specs:
            if self._match_path(spec.path, clean_path):
                matched_spec = spec
                break

        if matched_spec is None:
            return EndpointValidationResult(
                is_allowed=False,
                service=service,
                endpoint=path,
                method=method,
                reason=(
                    f"Zero-Guesswork violation: endpoint path '{clean_path}' is not in documented whitelist "
                    f"for service '{service}'. Blind probing rejected."
                ),
            )

        # Check allowed methods
        allowed_methods_upper = [m.upper() for m in matched_spec.allowed_methods]
        if req_method not in allowed_methods_upper:
            return EndpointValidationResult(
                is_allowed=False,
                service=service,
                endpoint=path,
                method=method,
                reason=(
                    f"Zero-Guesswork violation: HTTP method '{req_method}' not permitted for '{clean_path}'. "
                    f"Allowed methods: {matched_spec.allowed_methods}."
                ),
            )

        # Check contract method name if function_name specified
        if function_name and matched_spec.contract_functions:
            func_clean = function_name.strip()
            if func_clean not in matched_spec.contract_functions:
                return EndpointValidationResult(
                    is_allowed=False,
                    service=service,
                    endpoint=path,
                    method=method,
                    reason=(
                        f"Zero-Guesswork violation: contract method '{func_clean}' is not declared "
                        f"in documented ABI functions {matched_spec.contract_functions}."
                    ),
                )

        return EndpointValidationResult(
            is_allowed=True,
            service=service,
            endpoint=path,
            method=method,
            reason="Endpoint call matched documented whitelist specification.",
        )
