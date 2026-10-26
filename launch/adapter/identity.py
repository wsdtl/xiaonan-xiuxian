"""框架级身份解析端口。

launch 不依赖辅助路由；辅助路由启动时把解析器注册进来。QQ 驱动器在构造
MessageContext 时通过这里取统一身份，平台 user_id/reply_target 保持不变。
"""

from __future__ import annotations

from collections.abc import Callable

from launch import C, logger

IdentityResolver = Callable[[str, str], str | None]

_user_resolver: IdentityResolver | None = None
_group_resolver: IdentityResolver | None = None


def register_identity_resolver(
    *,
    user: IdentityResolver | None = None,
    group: IdentityResolver | None = None,
) -> None:
    """注册用户/群身份解析器；只覆盖传入的那一部分。"""

    global _user_resolver, _group_resolver
    if user is not None:
        _user_resolver = user
    if group is not None:
        _group_resolver = group


def clear_identity_resolver() -> None:
    """清空解析器；主要供测试和热重载使用。"""

    global _user_resolver, _group_resolver
    _user_resolver = None
    _group_resolver = None


def resolve_user_id(bot_key: str, openid: str) -> str:
    """官方 openid -> QQ 号；未接入或解析失败时返回空串。"""

    if _user_resolver is None:
        return ""
    try:
        value = _user_resolver(str(bot_key or ""), str(openid or ""))
    except Exception:  # noqa: BLE001 - 身份解析失败不能拖垮 QQ 命令
        logger.opt(colors=True).exception(
            C.join(
                C.warn("用户身份解析失败"),
                C.kv("bot", bot_key or "-"),
                C.kv("openid", openid or "-"),
            )
        )
        return ""
    return str(value or "").strip()


def route_fields(*, bot_key: str, user_id: str, group_id: str = "") -> dict[str, str]:
    """给 MessageContext 生成统一身份字段；各驱动器共用这一处。"""

    return {
        "route_user_id": resolve_user_id(bot_key, user_id),
        "route_group_id": (
            resolve_group_id(bot_key, group_id) if group_id else ""
        ),
    }


def resolve_group_id(bot_key: str, group_openid: str) -> str:
    """官方 group_openid -> QQ 群号；未接入或解析失败时返回空串。"""

    if _group_resolver is None:
        return ""
    try:
        value = _group_resolver(str(bot_key or ""), str(group_openid or ""))
    except Exception:  # noqa: BLE001 - 身份解析失败不能拖垮 QQ 命令
        logger.opt(colors=True).exception(
            C.join(
                C.warn("群身份解析失败"),
                C.kv("bot", bot_key or "-"),
                C.kv("group_openid", group_openid or "-"),
            )
        )
        return ""
    return str(value or "").strip()


__all__ = [
    "IdentityResolver",
    "clear_identity_resolver",
    "register_identity_resolver",
    "resolve_group_id",
    "route_fields",
    "resolve_user_id",
]
