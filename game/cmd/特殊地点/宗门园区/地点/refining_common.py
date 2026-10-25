"""宗门洞天生产设施命令。"""

from __future__ import annotations

from game.app import current_game_services
from game.features.zongmen_sheshi import FormationChoiceError, SectFacilityFeatureError

from . import refining_reply as reply
from launch.adapter import MessageContext
from typing import Any

_SOURCES = {"个人", "自备", "纳戒", "个人纳戒", "宗门", "灵藏", "宗门灵藏"}
_FORGING_STAGES = {"灵器", "法器", "法宝", "后天灵宝"}
_ALCHEMY_CATEGORIES = {"恢复丹", "战丹", "突破丹", "特殊丹"}
_GRADES = ("黄品", "玄品", "地品", "天品", "圣品")


def _parse_grade(identifier: str) -> tuple[str, str]:
    parts = identifier.split()
    if parts:
        token = parts[0]
        for name in _GRADES:
            short = name.removesuffix("品")
            for prefix in (name, short):
                if token.startswith(prefix):
                    rest = token[len(prefix):]
                    return name, " ".join(([rest] if rest else []) + parts[1:]).strip()
    return "黄品", identifier


_FACILITY_PAGE = {"炼器": "百炼堂", "炼丹": "丹鼎阁", "炼阵": "演阵台"}


async def dispatch(
    facility: str, user_id: str, query: str, request_id: str, manager: Any
) -> None:
    feature = current_game_services().features.zongmen_sheshi
    source, parts = _source(query)
    try:
        if facility == "炼器":
            if not parts:
                value = await feature.page(facility, user_id, source)
                await manager.send(reply.page(feature.copy(), value))
                return
            if parts[0] == "开炉":
                identifier = " ".join(parts[1:]).strip()
                if not identifier:
                    raise ValueError(feature.copy()["错误"]["需要器律"])
                value = await feature.craft(
                    facility, user_id, request_id, source, identifier
                )
                await manager.send(reply.completed(feature.copy(), value))
                return
            if parts[0] in _FORGING_STAGES:
                page = int(parts[1]) if len(parts) == 2 else 1
                value = await feature.page(facility, user_id, source, parts[0], page)
                await manager.send(reply.page(feature.copy(), value))
                return
            value = await feature.preview(facility, user_id, source, " ".join(parts))
            await manager.send(reply.preview(feature.copy(), value))
            return
        if facility == "炼丹":
            if not parts:
                value = await feature.page(facility, user_id, source)
                await manager.send(reply.page(feature.copy(), value))
                return
            if parts[0] == "开炉":
                identifier = " ".join(parts[1:]).strip()
                if not identifier:
                    raise ValueError(feature.copy()["错误"]["需要丹药"])
                grade, identifier = _parse_grade(identifier)
                value = await feature.craft(
                    facility, user_id, request_id, source, identifier, grade
                )
                await manager.send(reply.completed(feature.copy(), value))
                return
            if parts[0] in _ALCHEMY_CATEGORIES:
                page = int(parts[1]) if len(parts) == 2 else 1
                value = await feature.page(facility, user_id, source, parts[0], page)
                await manager.send(reply.page(feature.copy(), value))
                return
            grade, identifier = _parse_grade(" ".join(parts))
            value = await feature.preview(
                facility, user_id, source, identifier, grade
            )
            await manager.send(reply.preview(feature.copy(), value))
            return
        if not parts:
            value = await feature.page(facility, user_id, source)
            await manager.send(reply.page(feature.copy(), value))
            return
        action = parts[0]
        if action.isdigit() and len(parts) == 1:
            value = await feature.page(facility, user_id, source, page=int(action))
            await manager.send(reply.page(feature.copy(), value))
            return
        if action == "炼阵":
            parts = parts[1:]
            if not parts:
                raise ValueError(feature.copy()["错误"]["炼阵需要阵法"])
            grade, identifier = _parse_grade(parts[0])
            investments = _investments(parts[1:], feature.copy()["错误"]["圣品投入"])
            if investments and grade != "圣品":
                raise ValueError(
                    "黄品、玄品、地品、天品按固定配方炼制，不能追加兽宝、灵矿、灵植三数；"
                    "圣品才可追加"
                )
            value = await feature.craft(
                facility, user_id, request_id, source, identifier, grade, investments
            )
            await manager.send(reply.completed(feature.copy(), value))
            return
        if not parts:
            raise ValueError(feature.copy()["错误"]["审材需要阵法"])
        grade, identifier = _parse_grade(parts[0])
        investments = _investments(parts[1:], feature.copy()["错误"]["圣品投入"])
        if investments and grade != "圣品":
            raise ValueError(
                "黄品、玄品、地品、天品按固定配方炼制，不能追加兽宝、灵矿、灵植三数；"
                "圣品才可追加"
            )
        value = await feature.preview(
            facility, user_id, source, identifier, grade, investments
        )
        await manager.send(reply.preview(feature.copy(), value))
    except FormationChoiceError as exc:
        await manager.send(reply.choose(feature.copy(), exc))
    except (SectFacilityFeatureError, ValueError) as exc:
        await manager.send(
            reply.error(
                feature.copy(),
                str(exc),
                feature.format_actions(_FACILITY_PAGE[facility]),
            )
        )


def _source(query: str) -> tuple[str, list[str]]:
    parts = query.split()
    if parts and parts[0] in _SOURCES:
        return parts[0], parts[1:]
    return "个人", parts


def _investments(
    values: list[str], overflow_hint: str
) -> dict[str, int] | None:
    if not values:
        return None
    if len(values) != 3 or any(not value.isdigit() for value in values):
        raise ValueError(overflow_hint)
    return {"兽宝": int(values[0]), "灵矿": int(values[1]), "灵植": int(values[2])}


__all__ = ["dispatch"]
