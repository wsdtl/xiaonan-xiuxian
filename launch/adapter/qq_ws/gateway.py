"""QQ 网关协议：opcode、intents 与上下行 payload。

只做协议编解码和配置解释，不含连接管理与重连策略（在 runtime.py）。
字段名保持官方文档里的单字母 op/d/s/t/id，避免引入一套只在本地存在的
中间命名。
"""

from __future__ import annotations

import json
import sys
from typing import Any

from launch.config import config

# 官方 opcode 语义。
OP_DISPATCH = 0
OP_HEARTBEAT = 1
OP_IDENTIFY = 2
OP_RESUME = 6
OP_RECONNECT = 7
OP_INVALID_SESSION = 9
OP_HELLO = 10
OP_HEARTBEAT_ACK = 11
OP_HTTP_CALLBACK_ACK = 12
OP_WEBHOOK_VERIFY = 13

# 事件订阅位。基础权限只有 GUILDS / GUILD_MEMBERS / PUBLIC_GUILD_MESSAGES，
# 群聊与单聊消息、互动事件都需要单独权限位。
INTENT_FLAGS: dict[str, int] = {
    "GUILDS": 1 << 0,
    "GUILD_MEMBERS": 1 << 1,
    "GUILD_MESSAGES": 1 << 9,
    "GUILD_MESSAGE_REACTIONS": 1 << 10,
    "DIRECT_MESSAGE": 1 << 12,
    "GROUP_AND_C2C_EVENT": 1 << 25,
    "INTERACTION": 1 << 26,
    "MESSAGE_AUDIT": 1 << 27,
    "FORUMS_EVENT": 1 << 28,
    "AUDIO_ACTION": 1 << 29,
    "PUBLIC_GUILD_MESSAGES": 1 << 30,
}

# 只覆盖游戏真正处理的事件：单聊消息、群内 @ 机器人和按钮互动。
DEFAULT_INTENT_NAMES: tuple[str, ...] = ("GROUP_AND_C2C_EVENT", "INTERACTION")

# 客户端主动断开时的关闭码；QQ 用 4xxx 表示网关层错误。
CLOSE_NORMAL = 1000

# 官方错误码表里"可以重试 RESUME"的关闭码。其余 4xxx 一律必须重新 Identify：
# 带着服务端已经判定不可用的会话硬 Resume，只会再被拒一次。
RESUMABLE_CLOSE_CODES = frozenset({4008, 4009})

# "不可以连接"的关闭码：机器人下架（只允许沙箱）与封禁。这两种重连没有意义，
# 继续重试只会刷满日志，应当停下等平台侧处理。
FATAL_CLOSE_CODES = frozenset({4914, 4915})

# 本地链路断开、但会话未必失效的关闭码：正常关闭与"没有收到关闭帧就断链"。
# 这两种按 Resume 处理，让服务端补发这段空档里遗漏的事件。
RECONNECT_CLOSE_CODES = frozenset({1000, 1006})


class QqGatewayPayloadError(RuntimeError):
    """收到的网关 payload 不符合协议。"""


def build_identify(
    access_token: str,
    intents: int,
    shard: tuple[int, int],
) -> dict[str, Any]:
    """构造 op 2 鉴权 payload。"""

    return {
        "op": OP_IDENTIFY,
        "d": {
            "token": f"QQBot {access_token}",
            "intents": int(intents),
            "shard": [int(shard[0]), int(shard[1])],
            "properties": {
                "$os": sys.platform,
                "$browser": "xiaonan-xiuxian",
                "$device": "xiaonan-xiuxian",
            },
        },
    }


def build_resume(access_token: str, session_id: str, seq: int) -> dict[str, Any]:
    """构造 op 6 恢复连接 payload。"""

    return {
        "op": OP_RESUME,
        "d": {
            "token": f"QQBot {access_token}",
            "session_id": str(session_id),
            "seq": int(seq),
        },
    }


def build_heartbeat(seq: int | None) -> dict[str, Any]:
    """构造 op 1 心跳 payload；首次未收到事件时 d 为 null。"""

    return {"op": OP_HEARTBEAT, "d": None if seq is None else int(seq)}


def dumps(payload: dict[str, Any]) -> str:
    """序列化下行 payload。"""

    return json.dumps(payload, ensure_ascii=False)


def loads(raw: str | bytes) -> dict[str, Any]:
    """解析上行 payload；非 JSON 对象一律报错。"""

    try:
        payload = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise QqGatewayPayloadError("网关 payload 不是合法 JSON") from exc
    if not isinstance(payload, dict):
        raise QqGatewayPayloadError("网关 payload 必须是 JSON 对象")
    return payload


def payload_opcode(payload: dict[str, Any]) -> int:
    """读取 opcode；缺失或非法直接报错。"""

    try:
        return int(payload.get("op"))
    except (TypeError, ValueError) as exc:
        raise QqGatewayPayloadError(f"网关 payload 缺少合法 op：{payload.get('op')!r}") from exc


def payload_sequence(payload: dict[str, Any], fallback: int) -> int:
    """读取 s 序列号；缺失时保持上一次的值。"""

    value = payload.get("s")
    if value is None:
        return int(fallback)
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(fallback)


def payload_event(payload: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """读取 op 0 的事件类型与事件体。"""

    event_type = str(payload.get("t") or "").strip()
    data = payload.get("d")
    if not isinstance(data, dict):
        data = {}
    return event_type, data


def hello_interval_ms(payload: dict[str, Any]) -> int:
    """从 op 10 Hello 中读取心跳周期（毫秒）。"""

    data = payload.get("d")
    if not isinstance(data, dict):
        raise QqGatewayPayloadError("Hello payload 缺少 d 对象")
    try:
        interval = int(data.get("heartbeat_interval"))
    except (TypeError, ValueError) as exc:
        raise QqGatewayPayloadError("Hello payload 缺少 heartbeat_interval") from exc
    if interval <= 0:
        raise QqGatewayPayloadError(f"Hello heartbeat_interval 非法：{interval}")
    return interval


def ready_session(payload: dict[str, Any]) -> tuple[str, str]:
    """从 READY/RESUMED 事件里读取 session_id 与机器人自身 ID。"""

    _event_type, data = payload_event(payload)
    session_id = str(data.get("session_id") or "").strip()
    user = data.get("user") if isinstance(data.get("user"), dict) else {}
    self_id = str(user.get("id") or "").strip()
    return session_id, self_id


def invalid_session_resumable(payload: dict[str, Any]) -> bool:
    """读取 op 9 的 d 字段，判断是否还允许 Resume。"""

    return bool(payload.get("d"))


def resolve_intents() -> int:
    """按 `.env` 解释本驱动器要订阅的事件位。

    `QQ_WS_INTENTS` 既可以是 intent 名字列表（推荐，可读），也可以直接写
    十进制整数（需要精确定位时使用）。
    """

    raw = str(config.get("QQ_WS_INTENTS", "") or "").strip()
    if not raw:
        return named_intents(DEFAULT_INTENT_NAMES)

    if raw.isdigit():
        return int(raw)

    try:
        names = config.get_list("QQ_WS_INTENTS", DEFAULT_INTENT_NAMES)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "QQ_WS_INTENTS 必须是 intent 名字列表，或一个十进制整数"
        ) from exc
    if not names:
        raise ValueError("QQ_WS_INTENTS 不能是空列表")
    return named_intents(names)


def named_intents(names: tuple[str, ...] | list[str]) -> int:
    """把 intent 名字列表合成位掩码。"""

    intents = 0
    unknown: list[str] = []
    for name in names:
        key = str(name or "").strip().upper()
        if not key:
            continue
        if key not in INTENT_FLAGS:
            unknown.append(key)
            continue
        intents |= INTENT_FLAGS[key]
    if unknown:
        raise ValueError(
            f"QQ_WS_INTENTS 含未知 intent：{'、'.join(unknown)}；"
            f"可用值：{'、'.join(sorted(INTENT_FLAGS))}"
        )
    if not intents:
        raise ValueError("QQ_WS_INTENTS 未解析出任何 intent")
    return intents


def describe_intents(intents: int) -> str:
    """把位掩码转回可读名字，用于启动日志。"""

    names = [name for name, flag in INTENT_FLAGS.items() if intents & flag]
    return "、".join(names) if names else str(intents)


def gateway_url() -> str:
    """读取网关地址覆盖项；为空时走 OpenAPI 获取。

    配置项存在的意义是让本地回环网关和代理能被真实验证，不必改代码。
    """

    return str(config.get("QQ_WS_GATEWAY_URL", "") or "").strip()


__all__ = [
    "CLOSE_NORMAL",
    "DEFAULT_INTENT_NAMES",
    "FATAL_CLOSE_CODES",
    "INTENT_FLAGS",
    "OP_DISPATCH",
    "OP_HEARTBEAT",
    "OP_HEARTBEAT_ACK",
    "OP_HELLO",
    "OP_IDENTIFY",
    "OP_INVALID_SESSION",
    "OP_RECONNECT",
    "OP_RESUME",
    "QqGatewayPayloadError",
    "RECONNECT_CLOSE_CODES",
    "RESUMABLE_CLOSE_CODES",
    "build_heartbeat",
    "build_identify",
    "build_resume",
    "describe_intents",
    "dumps",
    "gateway_url",
    "hello_interval_ms",
    "invalid_session_resumable",
    "loads",
    "named_intents",
    "payload_event",
    "payload_opcode",
    "payload_sequence",
    "ready_session",
    "resolve_intents",
]
