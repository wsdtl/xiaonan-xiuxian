"""用户路由与群路由两套独立匹配；唯一匹配直接建立别名。"""

from __future__ import annotations

import re

from launch import C, logger

from .contracts import MatchResult, RouteEvent
from .store import AssistRouterStore

_SPACE = re.compile(r"\s+")


def _ambiguous(**fields: object) -> None:
    logger.opt(colors=True).debug(
        C.join(
            C.warn("辅助路由未唯一匹配"),
            C.kv("kind", fields.get("kind", "")),
            C.kv("reason", fields.get("reason", "")),
        )
    )


def normalize_text(text: str) -> str:
    return _SPACE.sub(" ", str(text or "").strip())


def _score(first: RouteEvent, second: RouteEvent) -> tuple[int, str]:
    """只按内容和时间打分；昵称不是可靠身份，不参与判断。"""

    delta = abs(first.occurred_at - second.occurred_at)
    score = 95 - min(35, int(delta * 10))
    return score, f"内容一致，时间差 {delta:.2f}s"


def _pair(event: RouteEvent, other: RouteEvent) -> tuple[RouteEvent, RouteEvent]:
    if event.source == "qq":
        return event, other
    return other, event


def match_user(
    event: RouteEvent,
    event_id: int,
    store: AssistRouterStore,
    *,
    window: float,
    confirm_score: int,
    auto_confirm: bool,
) -> MatchResult | None:
    other_source = "napcat" if event.source == "qq" else "qq"
    chat_id: str | None = None
    if event.scene == "group":
        if event.source == "qq":
            route = store.resolve_group(
                official_bot_key=event.bot_key, group_openid=event.chat_id
            )
            if route:
                chat_id = str(route["qq_group_id"])
        else:
            route = store.lookup_group_for_qq(event.chat_id)
            if route:
                chat_id = str(route["group_openid"])
    candidates = store.candidates(
        event, source=other_source, window=window, domain="user", chat_id=chat_id
    )
    if not candidates:
        return None
    if len(candidates) != 1:
        official_id = event_id if event.source == "qq" else candidates[0][0]
        napcat_id = candidates[0][0] if event.source == "qq" else event_id
        _ambiguous(
            kind="user",
            official_event_id=official_id,
            napcat_event_id=napcat_id,
            official_key=event.sender_id if event.source == "qq" else candidates[0][1].sender_id,
            napcat_key=candidates[0][1].sender_id if event.source == "qq" else event.sender_id,
            score=50,
            reason=f"候选 {len(candidates)} 个，未自动建立用户路由",
        )
        return None

    other_id, other = candidates[0]
    official, napcat = _pair(event, other)
    score, reason = _score(official, napcat)
    if score < confirm_score or not auto_confirm:
        _ambiguous(
            kind="user",
            official_event_id=event_id if event.source == "qq" else other_id,
            napcat_event_id=other_id if event.source == "qq" else event_id,
            official_key=official.sender_id,
            napcat_key=napcat.sender_id,
            score=score,
            reason=reason if score < confirm_score else reason + "，自动确认关闭",
        )
        return None

    existing = store.user_alias(
        official_bot_key=official.bot_key, openid=official.sender_id
    )
    if existing and str(existing["qq_uin"]) != napcat.sender_id:
        _ambiguous(
            kind="user",
            official_event_id=event_id if event.source == "qq" else other_id,
            napcat_event_id=other_id if event.source == "qq" else event_id,
            official_key=official.sender_id,
            napcat_key=napcat.sender_id,
            score=score,
            reason=f"与已有用户路由冲突：{existing['qq_uin']} vs {napcat.sender_id}",
        )
        return None

    store.upsert_user_alias(
        official_bot_key=official.bot_key,
        openid=official.sender_id,
        qq_uin=napcat.sender_id,
        scene=official.scene,
        group_openid=official.chat_id if official.scene == "group" else "",
        confidence=score,
        status="confirmed",
        evidence={
            "official_message_id": official.message_id,
            "napcat_message_id": napcat.message_id,
            "official_text": official.text,
            "official_time": official.occurred_at,
            "napcat_time": napcat.occurred_at,
            "reason": reason,
        },
    )
    store.mark_consumed("user", event_id, other_id)
    return MatchResult(
        official,
        napcat,
        score,
        reason,
        f"{official.bot_key}:{official.sender_id}",
    )


def match_group(
    event: RouteEvent,
    event_id: int,
    store: AssistRouterStore,
    *,
    window: float,
    confirm_score: int,
    auto_confirm: bool,
) -> MatchResult | None:
    if event.scene != "group":
        return None
    other_source = "napcat" if event.source == "qq" else "qq"
    candidates = store.candidates(
        event, source=other_source, window=window, domain="group"
    )
    if not candidates:
        return None
    official_id = event_id if event.source == "qq" else candidates[0][0]
    napcat_id = candidates[0][0] if event.source == "qq" else event_id
    official, napcat = _pair(event, candidates[0][1])
    score, reason = _score(official, napcat)

    if len(candidates) != 1:
        for other_id, other in candidates:
            official_event, napcat_event = _pair(event, other)
            _ambiguous(
                kind="group",
                official_event_id=event_id if event.source == "qq" else other_id,
                napcat_event_id=other_id if event.source == "qq" else event_id,
                official_key=official_event.chat_id,
                napcat_key=napcat_event.chat_id,
                score=score,
                reason=f"候选 {len(candidates)} 个，未自动建立群路由",
            )
        return None

    if not auto_confirm or score < confirm_score:
        _ambiguous(
            kind="group",
            official_event_id=official_id,
            napcat_event_id=napcat_id,
            official_key=official.chat_id,
            napcat_key=napcat.chat_id,
            score=score,
            reason=reason if score < confirm_score else reason + "，自动确认关闭",
        )
        return None

    existing = store.group_alias(
        official_bot_key=official.bot_key, group_openid=official.chat_id
    )
    if existing and str(existing["qq_group_id"]) != napcat.chat_id:
        _ambiguous(
            kind="group",
            official_event_id=official_id,
            napcat_event_id=napcat_id,
            official_key=official.chat_id,
            napcat_key=napcat.chat_id,
            score=score,
            reason=f"与已有群路由冲突：{existing['qq_group_id']} vs {napcat.chat_id}",
        )
        return None

    store.upsert_group_alias(
        official_bot_key=official.bot_key,
        group_openid=official.chat_id,
        qq_group_id=napcat.chat_id,
        confidence=score,
        status="confirmed",
        evidence={
            "official_message_id": official.message_id,
            "napcat_message_id": napcat.message_id,
            "official_text": official.text,
            "official_time": official.occurred_at,
            "napcat_time": napcat.occurred_at,
            "reason": reason,
        },
    )
    store.mark_consumed("group", official_id, napcat_id)
    return MatchResult(
        official,
        napcat,
        score,
        reason,
        f"{official.bot_key}:{official.chat_id}",
    )
