"""Natural Language → SecurityConfig policy generator.

Converts natural language security policy descriptions into structured
SecurityConfig JSON through LLM generation with validation and explanation.

Usage (framework-level — no LLM call, caller provides LLM integration):

    from myrm_agent_harness.agent.security.policy_generator import (
        build_messages,
        parse_policy_response,
        validate_generated_policy,
        explain_policy,
    )

    # 1. Build prompt messages
    messages = build_messages("禁止执行rm命令", current_config=existing_config)

    # 2. Call your LLM (framework doesn't couple to specific provider)
    llm_output = await your_llm_client.chat(messages)

    # 3. Parse response
    generated = parse_policy_response(llm_output)

    # 4. Validate
    is_valid, warnings = validate_generated_policy(generated, existing_config)

    # 5. Explain to user
    explanation = explain_policy(generated, locale="zh")
"""

from myrm_agent_harness.agent.security.policy_generator.explainer import (
    explain_policy,
)
from myrm_agent_harness.agent.security.policy_generator.parser import (
    PolicyParseError,
    parse_policy_response,
)
from myrm_agent_harness.agent.security.policy_generator.prompts import (
    build_messages,
)
from myrm_agent_harness.agent.security.policy_generator.validator import (
    PolicyWarning,
    WarningSeverity,
    validate_generated_policy,
)

__all__ = [
    "PolicyParseError",
    "PolicyWarning",
    "WarningSeverity",
    "build_messages",
    "explain_policy",
    "parse_policy_response",
    "validate_generated_policy",
]
