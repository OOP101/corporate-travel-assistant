"""无状态签名会话 Token —— 跨服务可验证的登录态

为什么需要：登录由 journey-hub 签发，但用户级数据（画像 / 行程 / 模板）由
planner-core 持有。若 token 只存签发进程的内存，planner 无从验证，且服务一重启
全体掉线。改为 HMAC 签名的自包含 token 后，任何持有同一 SESSION_SECRET 的进程
都能离线校验——单体模式天然满足，微服务模式各进程读同一份 .env 即可。

格式：base64url(json_payload) . base64url(hmac_sha256(payload_b64, secret))
base64url 字母表不含 "."，故用它做分隔符不会歧义。
"""
import base64
import hashlib
import hmac
import json
import time
from typing import Optional


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64d(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


class SignedSession:
    """签发 / 校验无状态会话 token。"""

    @staticmethod
    def encode(payload: dict, secret: str, ttl: int) -> str:
        body = {**payload, "exp": int(time.time()) + int(ttl)}
        payload_b64 = _b64e(
            json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        )
        sig = hmac.new(secret.encode("utf-8"), payload_b64.encode("ascii"), hashlib.sha256).digest()
        return f"{payload_b64}.{_b64e(sig)}"

    @staticmethod
    def decode(token: str, secret: str) -> Optional[dict]:
        """校验签名与过期；任一不满足返回 None。"""
        if not token or "." not in token:
            return None
        payload_b64, _, sig_b64 = token.partition(".")
        expected = hmac.new(
            secret.encode("utf-8"), payload_b64.encode("ascii"), hashlib.sha256
        ).digest()
        try:
            actual = _b64d(sig_b64)
        except Exception:
            return None
        # 定长比较，避免按字节比较提前返回带来的时序侧信道
        if not hmac.compare_digest(expected, actual):
            return None
        try:
            body = json.loads(_b64d(payload_b64))
        except Exception:
            return None
        if int(body.get("exp", 0)) < time.time():
            return None
        return body
