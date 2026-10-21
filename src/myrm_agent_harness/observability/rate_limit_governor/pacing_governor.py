"""
[INPUT]: Model configs, estimated request tokens, and provider header updates.
[OUTPUT]: QuotaPacingDecision shaping spike traffic into smooth streams and preventing 429 errors.
[POS]: myrm-agent-harness/src/myrm_agent_harness/observability/rate_limit_governor/pacing_governor.py
"""

from collections import deque
import threading
import time
from typing import Deque, Dict, Optional, Tuple

from .models import (
    GovernorLiveStatus,
    ModelRateLimitConfig,
    PacingAction,
    ProviderQuotaHeaderSnapshot,
    QuotaPacingDecision,
)


class ProactivePacingGovernor:
    """
    Sliding window token bucket and proactive traffic shaper that computes
    pacing decisions before sending requests, keeping multi-agent pipelines at zero 429s.
    """

    _DEFAULT_CONFIGS: Dict[str, ModelRateLimitConfig] = {
        "claude-3-5-sonnet": ModelRateLimitConfig(
            model_name="claude-3-5-sonnet",
            max_rpm=50,
            max_tpm=80_000,
            safe_watermark_pct=85.0,
        ),
        "deepseek-chat": ModelRateLimitConfig(
            model_name="deepseek-chat",
            max_rpm=120,
            max_tpm=200_000,
            safe_watermark_pct=85.0,
        ),
        "gpt-4o": ModelRateLimitConfig(
            model_name="gpt-4o",
            max_rpm=60,
            max_tpm=100_000,
            safe_watermark_pct=85.0,
        ),
    }

    _FALLBACK_CONFIG = ModelRateLimitConfig(
        model_name="generic-model",
        max_rpm=60,
        max_tpm=100_000,
        safe_watermark_pct=85.0,
    )

    def __init__(
        self,
        custom_configs: Optional[Dict[str, ModelRateLimitConfig]] = None,
        window_seconds: float = 60.0,
    ) -> None:
        self._lock = threading.Lock()
        self._window_seconds = window_seconds
        self._configs = dict(self._DEFAULT_CONFIGS)
        if custom_configs:
            self._configs.update(custom_configs)

        # Deque of (timestamp, token_count) per model
        self._token_windows: Dict[str, Deque[Tuple[float, int]]] = {}
        # Deque of timestamps for RPM per model
        self._request_windows: Dict[str, Deque[float]] = {}

        self._smoothed_counts: Dict[str, int] = {}
        self._prevented_429_counts: Dict[str, int] = {}

    def get_config(self, model_name: str) -> ModelRateLimitConfig:
        normalized = model_name.strip().lower()
        for k, v in self._configs.items():
            if k in normalized:
                return v
        return self._FALLBACK_CONFIG

    def _purge_expired(self, model_name: str, now: float) -> None:
        cutoff = now - self._window_seconds
        if model_name in self._token_windows:
            dq = self._token_windows[model_name]
            while dq and dq[0][0] < cutoff:
                dq.popleft()

        if model_name in self._request_windows:
            rq = self._request_windows[model_name]
            while rq and rq[0] < cutoff:
                rq.popleft()

    def evaluate_and_pace(
        self,
        model_name: str,
        estimated_prompt_tokens: int,
        fallback_model: Optional[str] = None,
    ) -> QuotaPacingDecision:
        with self._lock:
            now = time.time()
            self._purge_expired(model_name, now)
            cfg = self.get_config(model_name)

            t_window = self._token_windows.setdefault(model_name, deque())
            r_window = self._request_windows.setdefault(model_name, deque())

            current_tpm = sum(item[1] for item in t_window)
            current_rpm = len(r_window)

            projected_tpm = current_tpm + estimated_prompt_tokens
            tpm_watermark = round((projected_tpm / max(1, cfg.max_tpm)) * 100.0, 2)
            rpm_watermark = round(((current_rpm + 1) / max(1, cfg.max_rpm)) * 100.0, 2)

            # 1. Quota exhaustion check: projected tokens exceed maximum TPM limit
            if projected_tpm > cfg.max_tpm or current_rpm >= cfg.max_rpm:
                if fallback_model and fallback_model != model_name:
                    return QuotaPacingDecision(
                        action=PacingAction.FALLBACK_DOWNGRADE,
                        delay_ms=0,
                        current_tpm_usage=current_tpm,
                        max_tpm_limit=cfg.max_tpm,
                        tpm_watermark_pct=tpm_watermark,
                        current_rpm_usage=current_rpm,
                        max_rpm_limit=cfg.max_rpm,
                        reason=f"TPM 水位达 {tpm_watermark}% 触顶，推荐自动顺滑降级至备用模型 {fallback_model}。",
                        target_model_or_fallback=fallback_model,
                    )
                else:
                    return QuotaPacingDecision(
                        action=PacingAction.QUEUE_WAIT,
                        delay_ms=1000,
                        current_tpm_usage=current_tpm,
                        max_tpm_limit=cfg.max_tpm,
                        tpm_watermark_pct=tpm_watermark,
                        current_rpm_usage=current_rpm,
                        max_rpm_limit=cfg.max_rpm,
                        reason=f"TPM 水位达 {tpm_watermark}% 即将撞墙，主动排队等待滑动窗口释放。",
                        target_model_or_fallback=model_name,
                    )

            # 2. Proactive micro-sleep shaping: approaching safe watermark
            if tpm_watermark >= cfg.safe_watermark_pct or rpm_watermark >= cfg.safe_watermark_pct:
                self._smoothed_counts[model_name] = self._smoothed_counts.get(model_name, 0) + 1
                self._prevented_429_counts[model_name] = self._prevented_429_counts.get(model_name, 0) + 1
                return QuotaPacingDecision(
                    action=PacingAction.MICRO_SLEEP_PACED,
                    delay_ms=350,  # 350ms smooth micro-pacing
                    current_tpm_usage=current_tpm,
                    max_tpm_limit=cfg.max_tpm,
                    tpm_watermark_pct=tpm_watermark,
                    current_rpm_usage=current_rpm,
                    max_rpm_limit=cfg.max_rpm,
                    reason=f"水位达 {max(tpm_watermark, rpm_watermark)}% 接近安全预警线，主动施加 350ms 微整形削峰平流。",
                    target_model_or_fallback=model_name,
                )

            # 3. Healthy pass
            return QuotaPacingDecision(
                action=PacingAction.IMMEDIATE_PASS,
                delay_ms=0,
                current_tpm_usage=current_tpm,
                max_tpm_limit=cfg.max_tpm,
                tpm_watermark_pct=tpm_watermark,
                current_rpm_usage=current_rpm,
                max_rpm_limit=cfg.max_rpm,
                reason="配额水位安全健康，顺滑即时放行。",
                target_model_or_fallback=model_name,
            )

    def record_usage(self, model_name: str, actual_tokens: int) -> None:
        with self._lock:
            now = time.time()
            self._purge_expired(model_name, now)
            t_window = self._token_windows.setdefault(model_name, deque())
            r_window = self._request_windows.setdefault(model_name, deque())
            t_window.append((now, max(0, actual_tokens)))
            r_window.append(now)

    def update_from_header_snapshot(self, snapshot: ProviderQuotaHeaderSnapshot) -> None:
        with self._lock:
            if snapshot.remaining_tokens is not None:
                cfg = self.get_config(snapshot.model_name)
                computed_used = max(0, cfg.max_tpm - snapshot.remaining_tokens)
                t_window = self._token_windows.setdefault(snapshot.model_name, deque())
                # Recalibrate window with single synthetic balance if needed
                now = time.time()
                t_window.clear()
                t_window.append((now, computed_used))

    def get_live_status(self, model_name: str) -> GovernorLiveStatus:
        with self._lock:
            now = time.time()
            self._purge_expired(model_name, now)
            cfg = self.get_config(model_name)
            t_window = self._token_windows.get(model_name, deque())
            r_window = self._request_windows.get(model_name, deque())

            current_tpm = sum(item[1] for item in t_window)
            current_rpm = len(r_window)

            tpm_pct = round((current_tpm / max(1, cfg.max_tpm)) * 100.0, 2)
            rpm_pct = round((current_rpm / max(1, cfg.max_rpm)) * 100.0, 2)

            smoothed = self._smoothed_counts.get(model_name, 0)
            prevented = self._prevented_429_counts.get(model_name, 0)

            label = "✓ 绿灯顺畅放行" if tpm_pct < cfg.safe_watermark_pct else "⚠️ 削峰平流护航"

            return GovernorLiveStatus(
                model_name=cfg.model_name,
                tpm_watermark_pct=tpm_pct,
                rpm_watermark_pct=rpm_pct,
                smoothed_request_count=smoothed,
                prevented_429_count=prevented,
                active_subagent_slices_count=0,
                status_label=label,
            )
