"""BFF (Backend-For-Frontend) Auto-Refactor Engine for Client Secret Leaks.

[POS]
Automates surgical refactoring when hardcoded secrets are detected in browser code:
1. Extracts raw sensitive credentials into sandbox .env format.
2. Generates a secure, lightweight server-side API proxy route (Next.js / Node.js).
3. Rewrites the frontend client component to fetch via the internal relative proxy route.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from myrm_agent_harness.toolkits.code_execution.security.client_secret_scanner import (
    SecretFinding,
)


@dataclass(frozen=True)
class BffRefactorResult:
    """Outcome of automated BFF refactoring."""

    original_file_path: str
    refactored_client_code: str
    extracted_env_entries: dict[str, str]
    suggested_env_file_content: str
    server_proxy_file_path: str
    server_proxy_code: str
    refactor_explanation: str


class BffAutoRefactorEngine:
    """Engine that extracts hardcoded client credentials into a secure BFF proxy layer."""

    @classmethod
    def refactor(
        cls,
        code: str,
        file_path: str,
        findings: list[SecretFinding],
    ) -> BffRefactorResult:
        """Perform automated extraction of credentials and generate server-side proxy."""
        extracted_env: dict[str, str] = {}
        modified_code = code

        for finding in findings:
            env_var = finding.suggested_env_var
            # Assign fallback placeholder if masked
            extracted_env[env_var] = f"your_{env_var.lower()}_here"

        # Determine target proxy file path based on project structure
        norm_path = file_path.replace("\\", "/")
        if "app/" in norm_path or "src/app/" in norm_path:
            proxy_path = "src/app/api/proxy/route.ts" if "src/" in norm_path else "app/api/proxy/route.ts"
            proxy_endpoint = "/api/proxy"
        elif "pages/" in norm_path or "src/pages/" in norm_path:
            proxy_path = "src/pages/api/proxy.ts" if "src/" in norm_path else "pages/api/proxy.ts"
            proxy_endpoint = "/api/proxy"
        else:
            proxy_path = "server/api/proxy.js"
            proxy_endpoint = "/api/proxy"

        # Replace hardcoded direct API calls in client code
        # Pattern 1: replace https://api.openai.com/v1/... with /api/proxy
        modified_code = re.sub(
            r"""https://api\.openai\.com/v1/[a-zA-Z0-9_/]+""",
            proxy_endpoint,
            modified_code,
        )
        # Pattern 2: remove Authorization headers with hardcoded bearer tokens in client fetch
        modified_code = re.sub(
            r"""(?i)['"]Authorization['"]\s*:\s*[`'"]Bearer\s+(?:\$\{[^}]+\}|[a-zA-Z0-9_\-\.]+)[`'"]\s*,?""",
            "// Authorization handled securely by server-side BFF proxy",
            modified_code,
        )

        # Build .env content string
        env_lines = [f"{k}={v}" for k, v in extracted_env.items()]
        env_content = "\n".join(env_lines) + "\n"

        # Generate lightweight Next.js / Node.js BFF proxy code
        proxy_code = cls._generate_proxy_route_code(extracted_env)

        explanation = (
            f"Extracted {len(findings)} sensitive credential(s) from client-side file '{file_path}'. "
            f"Hardcoded tokens were replaced with calls to secure BFF proxy '{proxy_endpoint}'. "
            f"Credentials moved to environment variables."
        )

        return BffRefactorResult(
            original_file_path=file_path,
            refactored_client_code=modified_code,
            extracted_env_entries=extracted_env,
            suggested_env_file_content=env_content,
            server_proxy_file_path=proxy_path,
            server_proxy_code=proxy_code,
            refactor_explanation=explanation,
        )

    @classmethod
    def _generate_proxy_route_code(cls, env_entries: dict[str, str]) -> str:
        """Generate Next.js Route Handler code that forwards client requests with server secrets."""
        primary_key = next(iter(env_entries.keys()), "API_SECRET_KEY")
        return f"""import {{ NextResponse }} from "next/server";

/**
 * Secure Backend-For-Frontend (BFF) proxy route.
 * Injects server-side credentials and forwards requests to external services,
 * completely hiding secret keys from browser client-side code and devtools.
 */
export async function POST(request: Request) {{
  try {{
    const secretKey = process.env.{primary_key};
    if (!secretKey) {{
      return NextResponse.json(
        {{ error: "Missing server environment secret {primary_key}" }},
        {{ status: 500 }}
      );
    }}

    const body = await request.json();
    const targetUrl = "https://api.openai.com/v1/chat/completions";

    const response = await fetch(targetUrl, {{
      method: "POST",
      headers: {{
        "Content-Type": "application/json",
        Authorization: `Bearer ${{secretKey}}`,
      }},
      body: JSON.stringify(body),
    }});

    const data = await response.json();
    return NextResponse.json(data, {{ status: response.status }});
  }} catch (error) {{
    return NextResponse.json(
      {{ error: "Internal BFF proxy error", details: String(error) }},
      {{ status: 500 }}
    );
  }}
}}
"""
