"""Session lifecycle log archiver and offline bundle export engine.

Provides structured archiving, sensitive credential sanitization, self-contained
offline HTML and JSON bundle exports, and 1-click import replay verification.

[INPUT]
- runtime.context.session_data_sanitizer::SessionDataSanitizer (POS: Session data sanitization engine for
  confidential information masking.)
- runtime.context.session_lifecycle_log_archiver_types::ArtifactSnapshotEntry, ImportReplayResult,
  SanitizationPolicy, SessionExecutionTurn, SessionLogArchiveBundle, TokenCostBillingSnapshot,
  ToolExecutionLogEntry, ToolExecutionStatus (POS: Session lifecycle log archive and offline bundle export
  types.)

[OUTPUT]
- SessionLifecycleLogArchiverAndOfflineBundleExportEngine: Engine for archiving execution logs, exporting
  offline bundles, and importing sessions.

[POS]
Session lifecycle log archiver and offline bundle export engine.
"""

import hashlib
import html
import json
from datetime import UTC, datetime

from .session_data_sanitizer import SessionDataSanitizer
from .session_lifecycle_log_archiver_types import (
    ArtifactSnapshotEntry,
    ImportReplayResult,
    SanitizationPolicy,
    SessionExecutionTurn,
    SessionLogArchiveBundle,
    TokenCostBillingSnapshot,
    ToolExecutionLogEntry,
    ToolExecutionStatus,
)


class SessionLifecycleLogArchiverAndOfflineBundleExportEngine:
    """Engine for archiving execution logs, exporting offline bundles, and importing sessions."""

    def archive_session(
        self,
        session_id: str,
        workspace_name: str,
        created_at: str,
        turns: list[SessionExecutionTurn],
        artifacts: list[ArtifactSnapshotEntry],
        policy: SanitizationPolicy | None = None,
    ) -> SessionLogArchiveBundle:
        """Construct an archived session bundle with optional credential sanitization."""
        is_sanitized = False
        processed_turns = list(turns)
        processed_artifacts = list(artifacts)

        if policy is not None:
            sanitizer = SessionDataSanitizer(policy)
            processed_turns, processed_artifacts = sanitizer.sanitize_all(
                turns, artifacts
            )
            is_sanitized = True

        total_prompt = sum(t.token_billing.prompt_tokens for t in processed_turns)
        total_completion = sum(
            t.token_billing.completion_tokens for t in processed_turns
        )
        total_cache_hit = sum(
            t.token_billing.cache_hit_tokens for t in processed_turns
        )
        total_cost = sum(t.token_billing.estimated_cost_usd for t in processed_turns)

        total_billing = TokenCostBillingSnapshot(
            prompt_tokens=total_prompt,
            completion_tokens=total_completion,
            cache_hit_tokens=total_cache_hit,
            estimated_cost_usd=round(total_cost, 6),
        )

        exported_at = datetime.now(UTC).isoformat()
        raw_dict = self._bundle_to_dict_without_checksum(
            session_id=session_id,
            workspace_name=workspace_name,
            created_at=created_at,
            exported_at=exported_at,
            turns=processed_turns,
            artifacts=processed_artifacts,
            total_billing=total_billing,
            is_sanitized=is_sanitized,
        )
        checksum = self._compute_checksum(raw_dict)

        return SessionLogArchiveBundle(
            session_id=session_id,
            workspace_name=workspace_name,
            created_at=created_at,
            exported_at=exported_at,
            turns=processed_turns,
            artifacts=processed_artifacts,
            total_billing=total_billing,
            is_sanitized=is_sanitized,
            checksum_sha256=checksum,
        )

    def export_bundle_json(self, bundle: SessionLogArchiveBundle) -> str:
        """Serialize session bundle to a standardized JSON migration format."""
        bundle_dict = self._bundle_to_dict_without_checksum(
            session_id=bundle.session_id,
            workspace_name=bundle.workspace_name,
            created_at=bundle.created_at,
            exported_at=bundle.exported_at,
            turns=bundle.turns,
            artifacts=bundle.artifacts,
            total_billing=bundle.total_billing,
            is_sanitized=bundle.is_sanitized,
        )
        bundle_dict["checksum_sha256"] = bundle.checksum_sha256
        return json.dumps(bundle_dict, indent=2, ensure_ascii=False)

    def export_self_contained_html(self, bundle: SessionLogArchiveBundle) -> str:
        """Render a self-contained offline HTML report with embedded styles and interactivity."""
        turns_html: list[str] = []
        for turn in bundle.turns:
            tool_entries_html: list[str] = []
            for tool in turn.tool_calls:
                args_json = html.escape(json.dumps(tool.arguments, indent=2))
                payload = html.escape(tool.result_payload)
                tool_entries_html.append(
                    f"""<div class="tool-call">
  <div class="tool-header">
    <span class="tool-name">🔧 {html.escape(tool.tool_name)}</span>
    <span class="tool-status {tool.status.value.lower()}">{tool.status.value}</span>
    <span class="tool-duration">{tool.duration_ms:.1f}ms</span>
  </div>
  <details class="tool-details">
    <summary>Arguments & Return Payload</summary>
    <pre class="code-block">Arguments:\n{args_json}\n\nResult:\n{payload}</pre>
  </details>
</div>"""
                )

            tool_section = "\n".join(tool_entries_html)
            turns_html.append(
                f"""<div class="turn-card">
  <div class="turn-header">Round #{turn.turn_id} · <span class="time">{html.escape(turn.timestamp)}</span></div>
  <div class="message user"><strong>User:</strong> {html.escape(turn.user_input)}</div>
  <div class="message assistant"><strong>Assistant:</strong> {html.escape(turn.assistant_response)}</div>
  {tool_section}
  <div class="turn-tokens">Tokens: Prompt={turn.token_billing.prompt_tokens}, Completion={turn.token_billing.completion_tokens}, CacheHit={turn.token_billing.cache_hit_tokens}</div>
</div>"""
            )

        artifacts_html: list[str] = []
        for art in bundle.artifacts:
            artifacts_html.append(
                f"""<div class="artifact-card">
  <div class="artifact-header">📄 {html.escape(art.name)} <span class="mime">({html.escape(art.mime_type)})</span></div>
  <pre class="code-block">{html.escape(art.content_text)}</pre>
</div>"""
            )

        body_turns = "\n".join(turns_html)
        body_artifacts = "\n".join(artifacts_html)

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Myrm Session Report - {html.escape(bundle.session_id)}</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #0f172a; color: #f8fafc; margin: 0; padding: 24px; }}
  .container {{ max-width: 960px; margin: 0 auto; }}
  .header-box {{ background: #1e293b; padding: 20px; border-radius: 8px; margin-bottom: 24px; border: 1px solid #334155; }}
  .stats-row {{ display: flex; gap: 16px; margin-top: 12px; }}
  .stat-badge {{ background: #334155; padding: 6px 12px; border-radius: 4px; font-size: 14px; }}
  .turn-card {{ background: #1e293b; border-radius: 8px; padding: 16px; margin-bottom: 16px; border: 1px solid #334155; }}
  .turn-header {{ font-weight: bold; color: #38bdf8; margin-bottom: 8px; }}
  .message {{ margin: 8px 0; padding: 10px; border-radius: 6px; white-space: pre-wrap; }}
  .message.user {{ background: #0369a1; }}
  .message.assistant {{ background: #0f766e; }}
  .tool-call {{ background: #0f172a; border-left: 4px solid #6366f1; padding: 10px; margin: 8px 0; border-radius: 4px; }}
  .tool-header {{ display: flex; justify-content: space-between; font-size: 13px; }}
  .tool-status.success {{ color: #4ade80; }}
  .tool-status.failed {{ color: #f87171; }}
  .code-block {{ background: #020617; padding: 10px; border-radius: 4px; overflow-x: auto; font-family: monospace; font-size: 12px; }}
  .artifact-card {{ background: #1e293b; border: 1px solid #334155; border-radius: 8px; padding: 16px; margin-bottom: 16px; }}
  .turn-tokens {{ font-size: 12px; color: #94a3b8; margin-top: 8px; }}
</style>
</head>
<body>
<div class="container">
  <div class="header-box">
    <h2>Myrm Session Lifecycle Log: {html.escape(bundle.session_id)}</h2>
    <div>Workspace: <strong>{html.escape(bundle.workspace_name)}</strong> · Sanitized: <strong>{bundle.is_sanitized}</strong></div>
    <div class="stats-row">
      <div class="stat-badge">Total Tokens: {bundle.total_billing.total_tokens}</div>
      <div class="stat-badge">Cache Hit Tokens: {bundle.total_billing.cache_hit_tokens}</div>
      <div class="stat-badge">Estimated Cost: ${bundle.total_billing.estimated_cost_usd:.4f}</div>
      <div class="stat-badge">Checksum: {bundle.checksum_sha256[:12]}...</div>
    </div>
  </div>
  <h3>💬 Conversation Flow ({len(bundle.turns)} Turns)</h3>
  {body_turns}
  <h3>📦 Artifact Snapshots ({len(bundle.artifacts)})</h3>
  {body_artifacts}
</div>
</body>
</html>"""

    def import_and_verify(
        self, bundle_json_str: str
    ) -> tuple[SessionLogArchiveBundle | None, ImportReplayResult]:
        """Deserialize an archived session bundle and verify cryptographic integrity."""
        try:
            data = json.loads(bundle_json_str)
        except Exception as ex:
            return None, ImportReplayResult(
                session_id="",
                success=False,
                verified_checksum=False,
                turn_count=0,
                artifact_count=0,
                total_tokens=0,
                message=f"JSON decoding failed: {ex}",
            )

        recorded_checksum = data.get("checksum_sha256", "")
        clean_copy = dict(data)
        clean_copy.pop("checksum_sha256", None)

        computed_checksum = self._compute_checksum(clean_copy)
        if recorded_checksum != computed_checksum:
            return None, ImportReplayResult(
                session_id=data.get("session_id", "unknown"),
                success=False,
                verified_checksum=False,
                turn_count=0,
                artifact_count=0,
                total_tokens=0,
                message="Integrity check failed: checksum mismatch indicating file corruption or tampering",
            )

        turns: list[SessionExecutionTurn] = []
        for t in data.get("turns", []):
            tools: list[ToolExecutionLogEntry] = []
            for tool_data in t.get("tool_calls", []):
                tools.append(
                    ToolExecutionLogEntry(
                        call_id=tool_data["call_id"],
                        tool_name=tool_data["tool_name"],
                        arguments=tool_data["arguments"],
                        result_payload=tool_data["result_payload"],
                        duration_ms=tool_data["duration_ms"],
                        status=ToolExecutionStatus(tool_data["status"]),
                        timestamp=tool_data["timestamp"],
                        error_message=tool_data.get("error_message"),
                    )
                )

            tb_dict = t.get("token_billing", {})
            token_billing = TokenCostBillingSnapshot(
                prompt_tokens=tb_dict.get("prompt_tokens", 0),
                completion_tokens=tb_dict.get("completion_tokens", 0),
                cache_hit_tokens=tb_dict.get("cache_hit_tokens", 0),
                estimated_cost_usd=tb_dict.get("estimated_cost_usd", 0.0),
            )

            turns.append(
                SessionExecutionTurn(
                    turn_id=t["turn_id"],
                    user_input=t["user_input"],
                    assistant_response=t["assistant_response"],
                    tool_calls=tools,
                    token_billing=token_billing,
                    errors=t.get("errors", []),
                    timestamp=t.get("timestamp", ""),
                )
            )

        artifacts: list[ArtifactSnapshotEntry] = []
        for art_data in data.get("artifacts", []):
            artifacts.append(
                ArtifactSnapshotEntry(
                    artifact_id=art_data["artifact_id"],
                    name=art_data["name"],
                    mime_type=art_data["mime_type"],
                    content_text=art_data["content_text"],
                    version_hash=art_data["version_hash"],
                    created_at=art_data["created_at"],
                )
            )

        tot_billing_dict = data.get("total_billing", {})
        total_billing = TokenCostBillingSnapshot(
            prompt_tokens=tot_billing_dict.get("prompt_tokens", 0),
            completion_tokens=tot_billing_dict.get("completion_tokens", 0),
            cache_hit_tokens=tot_billing_dict.get("cache_hit_tokens", 0),
            estimated_cost_usd=tot_billing_dict.get("estimated_cost_usd", 0.0),
        )

        bundle = SessionLogArchiveBundle(
            session_id=data["session_id"],
            workspace_name=data.get("workspace_name", "default"),
            created_at=data.get("created_at", ""),
            exported_at=data.get("exported_at", ""),
            turns=turns,
            artifacts=artifacts,
            total_billing=total_billing,
            is_sanitized=data.get("is_sanitized", False),
            checksum_sha256=recorded_checksum,
        )

        return bundle, ImportReplayResult(
            session_id=bundle.session_id,
            success=True,
            verified_checksum=True,
            turn_count=len(turns),
            artifact_count=len(artifacts),
            total_tokens=total_billing.total_tokens,
            message="Session bundle successfully restored and verified with 100% integrity",
        )

    def _bundle_to_dict_without_checksum(
        self,
        session_id: str,
        workspace_name: str,
        created_at: str,
        exported_at: str,
        turns: list[SessionExecutionTurn],
        artifacts: list[ArtifactSnapshotEntry],
        total_billing: TokenCostBillingSnapshot,
        is_sanitized: bool,
    ) -> dict[str, object]:
        """Convert components into a serializable dictionary excluding checksum."""
        turns_list: list[dict[str, object]] = []
        for t in turns:
            tools_list: list[dict[str, object]] = []
            for tc in t.tool_calls:
                tools_list.append(
                    {
                        "call_id": tc.call_id,
                        "tool_name": tc.tool_name,
                        "arguments": tc.arguments,
                        "result_payload": tc.result_payload,
                        "duration_ms": tc.duration_ms,
                        "status": tc.status.value,
                        "timestamp": tc.timestamp,
                        "error_message": tc.error_message,
                    }
                )

            turns_list.append(
                {
                    "turn_id": t.turn_id,
                    "user_input": t.user_input,
                    "assistant_response": t.assistant_response,
                    "tool_calls": tools_list,
                    "token_billing": {
                        "prompt_tokens": t.token_billing.prompt_tokens,
                        "completion_tokens": t.token_billing.completion_tokens,
                        "cache_hit_tokens": t.token_billing.cache_hit_tokens,
                        "estimated_cost_usd": t.token_billing.estimated_cost_usd,
                    },
                    "errors": t.errors,
                    "timestamp": t.timestamp,
                }
            )

        artifacts_list: list[dict[str, object]] = [
            {
                "artifact_id": a.artifact_id,
                "name": a.name,
                "mime_type": a.mime_type,
                "content_text": a.content_text,
                "version_hash": a.version_hash,
                "created_at": a.created_at,
            }
            for a in artifacts
        ]

        return {
            "session_id": session_id,
            "workspace_name": workspace_name,
            "created_at": created_at,
            "exported_at": exported_at,
            "turns": turns_list,
            "artifacts": artifacts_list,
            "total_billing": {
                "prompt_tokens": total_billing.prompt_tokens,
                "completion_tokens": total_billing.completion_tokens,
                "cache_hit_tokens": total_billing.cache_hit_tokens,
                "estimated_cost_usd": total_billing.estimated_cost_usd,
            },
            "is_sanitized": is_sanitized,
        }

    def _compute_checksum(self, data_dict: dict[str, object]) -> str:
        """Compute SHA-256 fingerprint over canonical JSON serialization."""
        canonical_json = json.dumps(
            data_dict, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )
        return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
