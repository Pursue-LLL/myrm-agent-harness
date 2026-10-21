"""Unit tests for ClientSideSecretScanner, ClientSecretWriteValidator, and BffAutoRefactorEngine."""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.meta_tools.file_ops.core.operation_context import (
    OperationContext,
    OperationType,
    StrReplaceEdit,
)
from myrm_agent_harness.agent.meta_tools.file_ops.validators.client_secret_validator import (
    ClientSecretLeakViolationError,
    ClientSecretWriteValidator,
)
from myrm_agent_harness.toolkits.code_execution.security.bff_refactor import (
    BffAutoRefactorEngine,
)
from myrm_agent_harness.toolkits.code_execution.security.client_secret_scanner import (
    ClientSideSecretScanner,
)


def test_client_secret_scanner_detection_patterns() -> None:
    """Verify detection of various hardcoded credential patterns in client-facing code."""
    # 1. OpenAI Secret Key in React component
    react_code = """
import React, { useState } from 'react';

export default function ChatWidget() {
  const apiKey = "sk-proj-AbCdEfGhIjKlMnOpQrStUvWxYz1234567890AbCdEfGh";

  async function sendMessage() {
    const res = await fetch("https://api.openai.com/v1/chat/completions", {
      method: "POST",
      headers: {
        "Authorization": `Bearer ${apiKey}`,
      }
    });
  }
  return <div>Chat</div>;
}
"""
    findings = ClientSideSecretScanner.scan_code(react_code, "src/components/ChatWidget.tsx")
    assert len(findings) >= 1
    openai_finding = findings[0]
    assert openai_finding.secret_type == "OpenAI API Key"
    assert openai_finding.line_number == 5
    assert openai_finding.suggested_env_var == "OPENAI_API_KEY"

    # 2. Stripe and Database URL in Vue component
    vue_code = """
<template>
  <button @click="pay">Checkout</button>
</template>
<script>
export default {
  data() {
    return {
      stripeKey: "sk_live_123456789012345678901234",
      dbUrl: "postgresql://postgres:mysecretpassword@db.supabase.co:5432/production"
    }
  }
}
</script>
"""
    vue_findings = ClientSideSecretScanner.scan_code(vue_code, "src/views/Checkout.vue")
    assert len(vue_findings) == 2
    types = [f.secret_type for f in vue_findings]
    assert "Stripe Secret Key" in types
    assert "Database Connection URL" in types

    # 3. Clean code should produce zero findings
    clean_code = """
export default function SafeComponent() {
  return <div>Clean Content</div>;
}
"""
    assert len(ClientSideSecretScanner.scan_code(clean_code, "src/components/Safe.tsx")) == 0

    # 4. Server-only file paths should be skipped
    assert len(ClientSideSecretScanner.scan_code(react_code, "src/app/api/chat/route.ts")) == 0
    assert len(ClientSideSecretScanner.scan_code(react_code, "server/handlers.server.ts")) == 0


@pytest.mark.asyncio
async def test_client_secret_write_validator_blocks_mutation() -> None:
    """Verify validator physically raises ClientSecretLeakViolationError on file write."""
    validator = ClientSecretWriteValidator()

    leaked_tsx = """
export function Header() {
  const token = "ghp_123456789012345678901234567890123456";
  return <header>Header</header>;
}
"""
    # 1. CREATE operation should be blocked
    create_ctx = OperationContext(
        operation=OperationType.CREATE,
        executor=None,
        path="src/components/Header.tsx",
        file_text=leaked_tsx,
    )
    with pytest.raises(ClientSecretLeakViolationError) as exc_info:
        await validator.validate(create_ctx, "src/components/Header.tsx")

    err = str(exc_info.value)
    assert "CRITICAL_SECURITY_LEAK" in err
    assert "GitHub Personal Access Token" in err
    assert "REQUIRED ACTION: Extract credentials to sandbox .env" in err

    # 2. STR_REPLACE operation should be blocked
    replace_ctx = OperationContext(
        operation=OperationType.STR_REPLACE,
        executor=None,
        path="src/components/Header.tsx",
        edits=(StrReplaceEdit(old_str="placeholder", new_str=leaked_tsx),),
    )
    with pytest.raises(ClientSecretLeakViolationError):
        await validator.validate(replace_ctx, "src/components/Header.tsx")

    # 3. Safe content on client code should pass without error
    safe_ctx = OperationContext(
        operation=OperationType.CREATE,
        executor=None,
        path="src/components/Header.tsx",
        file_text="export const API_URL = '/api/v1/posts';",
    )
    await validator.validate(safe_ctx, "src/components/Header.tsx")

    # 4. VIEW operations should not trigger write validation
    view_ctx = OperationContext(
        operation=OperationType.VIEW,
        executor=None,
        paths=["src/components/Header.tsx"],
    )
    await validator.validate(view_ctx, "src/components/Header.tsx")


def test_bff_auto_refactor_engine() -> None:
    """Verify automated extraction to .env and Next.js / Node.js BFF proxy generation."""
    leaked_code = """
import React from 'react';

export function Assistant() {
  const apiKey = "sk-proj-1234567890123456789012345678901234567890";

  async function callAI() {
    return await fetch("https://api.openai.com/v1/chat/completions", {
      method: "POST",
      headers: { "Authorization": `Bearer ${apiKey}` },
      body: JSON.stringify({ prompt: "Hello" })
    });
  }
  return <div>AI</div>;
}
"""
    findings = ClientSideSecretScanner.scan_code(leaked_code, "src/app/assistant/page.tsx")
    assert len(findings) >= 1

    result = BffAutoRefactorEngine.refactor(
        code=leaked_code,
        file_path="src/app/assistant/page.tsx",
        findings=findings,
    )

    # 1. Assert extracted .env entries
    assert "OPENAI_API_KEY" in result.extracted_env_entries
    assert "OPENAI_API_KEY=" in result.suggested_env_file_content

    # 2. Assert generated server proxy route
    assert result.server_proxy_file_path == "src/app/api/proxy/route.ts"
    assert "export async function POST" in result.server_proxy_code
    assert "process.env.OPENAI_API_KEY" in result.server_proxy_code

    # 3. Assert client code refactoring
    assert "/api/proxy" in result.refactored_client_code
    assert "https://api.openai.com/v1/chat/completions" not in result.refactored_client_code
    assert "Authorization handled securely by server-side BFF proxy" in result.refactored_client_code
