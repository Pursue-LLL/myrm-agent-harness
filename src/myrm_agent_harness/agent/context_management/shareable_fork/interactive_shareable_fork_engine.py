"""核心引擎实现：具备交互式运行时状态的会话免密分享链接、多端只读/协作穿透与一键无损分叉。

[INPUT]
- 依赖 shareable_fork_types.py 中的契约，标准库 hmac, hashlib, datetime, uuid 等。

[OUTPUT]
- InteractiveShareableForkEngine: 交互式会话分享与无损分叉中枢引擎

[POS]
- 位于 context_management/shareable_fork/interactive_shareable_fork_engine.py
"""

from datetime import datetime, timedelta, timezone
import hashlib
import hmac
from typing import Sequence
import uuid

from .shareable_fork_types import (
    LosslessForkResult,
    ShareAccessPermission,
    ShareTokenPayload,
    ShareableForkConfig,
    SharedSessionPerspective,
)


class InteractiveShareableForkEngine:
    """交互式会话分享与无损分叉中枢引擎。

    彻底破除传统 AI 工具会话分享只能生成静态长图或只读网页、接收方无法在中间状态上
    接力继续跑、以及协作过程中上下文相互干扰污染的协作断层顽疾。
    """

    def __init__(self, config: ShareableForkConfig | None = None) -> None:
        self.config = config or ShareableForkConfig()
        # 分叉历史账本: forked_session_id -> LosslessForkResult
        self._fork_ledger: dict[str, LosslessForkResult] = {}

    def generate_share_token(
        self,
        session_id: str,
        issuer_id: str,
        permission: ShareAccessPermission = ShareAccessPermission.ALLOW_INTERACTIVE_FORK,
        include_artifacts: bool = True,
        ttl_seconds: int | None = None,
        share_id: str | None = None,
    ) -> ShareTokenPayload:
        """生成带 HMAC-SHA256 密码学签名的免密安全分享凭证。"""
        assigned_share_id = share_id or f"share_{uuid.uuid4().hex[:12]}"
        ttl = ttl_seconds if ttl_seconds is not None else self.config.default_ttl_seconds
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl)
        expires_iso = expires_at.isoformat()

        raw_payload = self._compute_signature_base(
            share_id=assigned_share_id,
            session_id=session_id,
            issuer_id=issuer_id,
            permission=permission,
            include_artifacts=include_artifacts,
            expires_at_iso=expires_iso,
        )
        sig = hmac.new(
            self.config.secret_key.encode("utf-8"),
            raw_payload.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        return ShareTokenPayload(
            share_id=assigned_share_id,
            session_id=session_id,
            issuer_id=issuer_id,
            permission=permission,
            include_artifacts=include_artifacts,
            expires_at_iso=expires_iso,
            signature_hmac=sig,
        )

    def verify_and_resolve_share(
        self,
        share_token: ShareTokenPayload,
        session_title: str,
        messages: Sequence[tuple[str, str]],  # (role, content)
        artifacts: Sequence[tuple[str, str]] | None = None,  # (name, uri)
    ) -> SharedSessionPerspective:
        """校验密码学凭证有效性，并组装高保真交互式只读透视视口。"""
        # 1. 签名校验
        expected_raw = self._compute_signature_base(
            share_id=share_token.share_id,
            session_id=share_token.session_id,
            issuer_id=share_token.issuer_id,
            permission=share_token.permission,
            include_artifacts=share_token.include_artifacts,
            expires_at_iso=share_token.expires_at_iso,
        )
        expected_sig = hmac.new(
            self.config.secret_key.encode("utf-8"),
            expected_raw.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        if not hmac.compare_digest(expected_sig, share_token.signature_hmac):
            raise PermissionError("Invalid share token cryptographic signature.")

        # 2. 时效过期校验
        expires_dt = datetime.fromisoformat(share_token.expires_at_iso)
        if datetime.now(timezone.utc) > expires_dt:
            raise TimeoutError(f"Share token {share_token.share_id} has expired.")

        # 3. 组装透视数据
        limited_messages = tuple(messages[: self.config.max_messages_snapshot])
        resolved_artifacts = (
            tuple(artifacts)
            if (artifacts and share_token.include_artifacts)
            else ()
        )

        trace_summary = (
            f"Perspective for session '{session_title}' ({share_token.session_id}): "
            f"{len(limited_messages)} turns, {len(resolved_artifacts)} artifacts attached."
        )

        can_fork = share_token.permission == ShareAccessPermission.ALLOW_INTERACTIVE_FORK

        return SharedSessionPerspective(
            share_id=share_token.share_id,
            session_id=share_token.session_id,
            session_title=session_title,
            messages_snapshot=limited_messages,
            artifacts_snapshot=resolved_artifacts,
            execution_trace_summary=trace_summary,
            can_fork=can_fork,
            expires_at_iso=share_token.expires_at_iso,
        )

    def execute_lossless_fork(
        self,
        perspective: SharedSessionPerspective,
        target_user_id: str,
        forked_session_id: str | None = None,
    ) -> LosslessForkResult:
        """执行一键无损分叉，派生独立子分支会话，实现团队无缝接力探索。"""
        if not perspective.can_fork:
            raise PermissionError(
                f"Share {perspective.share_id} does not permit lossless forking (read-only)."
            )

        # 检查是否过期
        expires_dt = datetime.fromisoformat(perspective.expires_at_iso)
        if datetime.now(timezone.utc) > expires_dt:
            raise TimeoutError(f"Share {perspective.share_id} has expired; fork denied.")

        assigned_fid = forked_session_id or f"fork_{perspective.session_id}_{uuid.uuid4().hex[:8]}"
        now_iso = datetime.now(timezone.utc).isoformat()

        result = LosslessForkResult(
            forked_session_id=assigned_fid,
            original_session_id=perspective.session_id,
            forked_by_user_id=target_user_id,
            copied_message_count=len(perspective.messages_snapshot),
            copied_artifact_count=len(perspective.artifacts_snapshot),
            new_session_uri=f"session://{assigned_fid}",
            forked_at_iso=now_iso,
        )

        self._fork_ledger[assigned_fid] = result
        return result

    def get_fork_record(self, forked_session_id: str) -> LosslessForkResult | None:
        """查询指定分叉会话的血缘追溯记录。"""
        return self._fork_ledger.get(forked_session_id)

    def _compute_signature_base(
        self,
        share_id: str,
        session_id: str,
        issuer_id: str,
        permission: ShareAccessPermission,
        include_artifacts: bool,
        expires_at_iso: str,
    ) -> str:
        """计算规范化签名基底字符串。"""
        return (
            f"{share_id}:{session_id}:{issuer_id}:"
            f"{permission.value}:{int(include_artifacts)}:{expires_at_iso}"
        )
