"""请求签名验证器

使用 HMAC-SHA256 验证请求的完整性和真实性。

签名流程：
1. 客户端：生成签名字符串 = method + path + timestamp + nonce + body
2. 客户端：使用 HMAC-SHA256 计算签名
3. 客户端：在 X-Signature 请求头中发送签名
4. 服务端：重新计算签名并对比

防护能力：
-  防止请求内容篡改
-  防止中间人攻击
-  防止请求参数注入

[INPUT]
- (none)

[OUTPUT]
- SignatureVerifier: Signature verifier protocol.
- TimestampVerifier: class — Timestamp Verifier

[POS]
Provides SignatureVerifier, TimestampVerifier.
"""

from __future__ import annotations

import hashlib
import hmac
import logging

from fastapi import Request

logger = logging.getLogger(__name__)


class SignatureVerifier:
    """请求签名验证器"""

    def __init__(self, secret_key: str) -> None:
        """初始化签名验证器

        Args:
            secret_key: 签名密钥（与 JWT_SECRET 相同）
        """
        self.secret_key = secret_key

    def generate_signature(
        self,
        method: str,
        path: str,
        timestamp: str,
        nonce: str,
        body: str = "",
    ) -> str:
        """生成请求签名

        Args:
            method: HTTP 方法（GET, POST, etc.）
            path: 请求路径
            timestamp: 时间戳
            nonce: Nonce
            body: 请求体（JSON 字符串）

        Returns:
            HMAC-SHA256 签名（十六进制）
        """
        sign_string = f"{method}\n{path}\n{timestamp}\n{nonce}\n{body}"

        signature = hmac.new(
            self.secret_key.encode("utf-8"),
            sign_string.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        return signature

    async def verify_request(
        self,
        request: Request,
        timestamp: str,
        nonce: str,
        signature: str,
    ) -> tuple[bool, str]:
        """验证请求签名

        Args:
            request: FastAPI 请求对象
            timestamp: 时间戳
            nonce: Nonce
            signature: 客户端提供的签名

        Returns:
            (验证结果, 错误信息)
        """
        try:
            body = await request.body()
            body_str = body.decode("utf-8") if body else ""

            server_signature = self.generate_signature(
                method=request.method,
                path=str(request.url.path),
                timestamp=timestamp,
                nonce=nonce,
                body=body_str,
            )

            if not hmac.compare_digest(signature, server_signature):
                logger.warning(
                    f" Signature verification failed: expected={server_signature[:16]}..., got={signature[:16]}..."
                )
                return False, "Invalid signature"

            logger.debug(f" Signature verified: {signature[:16]}...")
            return True, ""

        except Exception as e:
            logger.error(f" Signature verification error: {e}")
            return False, f"Signature verification error: {e!s}"


class TimestampVerifier:
    """时间戳验证器

    验证请求时间戳是否在允许的时间窗口内。
    """

    def __init__(self, time_window: int = 60) -> None:
        """初始化时间戳验证器

        Args:
            time_window: 允许的时间窗口（秒）
        """
        self.time_window = time_window

    def verify(self, timestamp: str) -> tuple[bool, str]:
        """验证时间戳

        Args:
            timestamp: Unix 时间戳（秒）

        Returns:
            (验证结果, 错误信息)
        """
        try:
            import time

            request_time = int(timestamp)
            current_time = int(time.time())

            time_diff = abs(current_time - request_time)

            if time_diff > self.time_window:
                logger.warning(f" Timestamp out of window: diff={time_diff}s, window={self.time_window}s")
                return False, f"Timestamp out of window (diff: {time_diff}s)"

            logger.debug(f" Timestamp verified: {timestamp} (diff: {time_diff}s)")
            return True, ""

        except ValueError:
            logger.warning(f" Invalid timestamp format: {timestamp}")
            return False, "Invalid timestamp format"
        except Exception as e:
            logger.error(f" Timestamp verification error: {e}")
            return False, f"Timestamp verification error: {e!s}"


__all__ = ["SignatureVerifier", "TimestampVerifier"]
