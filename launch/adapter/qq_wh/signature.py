"""QQ 回调地址验证签名工具。"""

import math
import time

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric import ed25519

SIGNATURE_HEADER = "X-Signature-Ed25519"
TIMESTAMP_HEADER = "X-Signature-Timestamp"
EVENT_SIGNATURE_MAX_AGE_SECONDS = 300.0


def make_validation_signature(bot_secret: str, plain_token: str, event_ts: str) -> str:
    """生成 QQ 回调验证签名。

    QQ 开放平台验证回调地址时会给 plain_token 和 event_ts；服务端用
    Bot Secret 派生 Ed25519 私钥，对 event_ts + plain_token 签名后返回。
    """

    seed = _secret_seed(bot_secret)
    private_key = ed25519.Ed25519PrivateKey.from_private_bytes(seed)
    message = f"{event_ts}{plain_token}".encode()
    return private_key.sign(message).hex()


def make_event_signature(bot_secret: str, timestamp: str, body: bytes) -> str:
    """生成 QQ 普通事件请求签名，主要供本地测试使用。"""

    private_key = _private_key(bot_secret)
    return private_key.sign(_event_signing_message(timestamp, body)).hex()


def verify_event_signature(
    bot_secret: str,
    timestamp: str,
    body: bytes,
    signature: str,
    *,
    now: float | None = None,
    max_age_seconds: float = EVENT_SIGNATURE_MAX_AGE_SECONDS,
) -> None:
    """校验 QQ 普通事件请求签名。

    QQ 普通事件回调通过请求头携带 Ed25519 签名。验签必须使用原始
    HTTP body，不能把 JSON 重新序列化后再验。
    """

    _verify_timestamp_freshness(timestamp, now=now, max_age_seconds=max_age_seconds)

    value = str(signature or "").strip()
    if not value:
        raise ValueError(f"缺少 {SIGNATURE_HEADER}")
    try:
        signature_bytes = bytes.fromhex(value)
    except ValueError as exc:
        raise ValueError(f"{SIGNATURE_HEADER} 不是合法 hex") from exc

    public_key = _private_key(bot_secret).public_key()
    try:
        public_key.verify(signature_bytes, _event_signing_message(timestamp, body))
    except InvalidSignature as exc:
        raise ValueError("QQ 普通事件签名校验失败") from exc


def _verify_timestamp_freshness(
    timestamp: str,
    *,
    now: float | None,
    max_age_seconds: float,
) -> None:
    """拒绝时间窗外的合法签名，避免普通事件被长期重放。"""

    value = str(timestamp or "").strip()
    if not value:
        raise ValueError(f"缺少 {TIMESTAMP_HEADER}")
    try:
        timestamp_value = float(value)
    except ValueError as exc:
        raise ValueError(f"{TIMESTAMP_HEADER} 不是合法 Unix 时间戳") from exc
    if not math.isfinite(timestamp_value):
        raise ValueError(f"{TIMESTAMP_HEADER} 不是合法 Unix 时间戳")

    current = time.time() if now is None else float(now)
    if abs(current - timestamp_value) > float(max_age_seconds):
        raise ValueError("QQ 普通事件签名时间戳已过期")


def _event_signing_message(timestamp: str, body: bytes) -> bytes:
    value = str(timestamp or "").strip()
    if not value:
        raise ValueError(f"缺少 {TIMESTAMP_HEADER}")
    if not isinstance(body, bytes):
        raise TypeError("QQ 签名校验 body 必须是原始 bytes")
    return value.encode("utf-8") + body


def _private_key(bot_secret: str) -> ed25519.Ed25519PrivateKey:
    return ed25519.Ed25519PrivateKey.from_private_bytes(_secret_seed(bot_secret))


def _secret_seed(bot_secret: str) -> bytes:
    """按 QQ 示例逻辑扩展 Bot Secret，直到 Ed25519 种子达到 32 字节。"""

    secret = bot_secret.strip()
    if not secret:
        raise ValueError("QQ bot secret 不能为空")

    seed = secret.encode("utf-8")
    while len(seed) < 32:
        seed += seed
    return seed[:32]
