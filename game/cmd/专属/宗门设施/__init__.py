"""宗门洞天生产设施命令。"""

from __future__ import annotations

from game.app import current_game_services
from game.features.zongmen_sheshi import SectFacilityFeatureError

from ...command import GameCommand
from . import reply

_SOURCES = {"个人", "自备", "纳戒", "个人纳戒", "宗门", "灵藏", "宗门灵藏"}
_FORGING_STAGES = {"灵器", "法器", "法宝", "后天灵宝"}
_ALCHEMY_CATEGORIES = {"恢复丹", "战丹", "突破丹", "特殊丹"}


@GameCommand.command(
    cmd="百炼堂",
    metadata={
        "scope": "专属",
        "guard_rule": "自主空闲或休息",
        "help": {
            "category": "炼制",
            "summary": "在百炼堂炼制本命武器器律",
            "usage": ("百炼堂", "百炼堂 宗门", "百炼堂 灵器", "百炼堂 开炉 器律编号"),
            "side_effect": "按次消耗宗门灵石；材料来源按个人或宗门路径结算",
            "order": 74,
        },
    },
)
async def bailiantang(
    *, user_id: str, message: str, message_context, manager, **_
) -> None:
    await _dispatch(
        "炼器", user_id, str(message or "").strip(), message_context.request_id, manager
    )


@GameCommand.command(
    cmd="丹鼎阁",
    metadata={
        "scope": "专属",
        "guard_rule": "自主空闲或休息",
        "help": {
            "category": "炼制",
            "summary": "在丹鼎阁炼制丹药",
            "usage": ("丹鼎阁", "丹鼎阁 宗门", "丹鼎阁 恢复丹", "丹鼎阁 开炉 丹方编号"),
            "side_effect": "按次消耗宗门灵石；材料来源按个人或宗门路径结算",
            "order": 75,
        },
    },
)
async def dandingge(
    *, user_id: str, message: str, message_context, manager, **_
) -> None:
    await _dispatch(
        "炼丹", user_id, str(message or "").strip(), message_context.request_id, manager
    )


@GameCommand.command(
    cmd="演阵台",
    metadata={
        "scope": "专属",
        "guard_rule": "自主空闲或休息",
        "help": {
            "category": "炼制",
            "summary": "在演阵台炼制一次性阵法",
            "usage": ("演阵台", "演阵台 宗门", "演阵台 1", "演阵台 炼阵 阵法编号 圣"),
            "side_effect": "按次消耗宗门灵石；圣品按实际三相投入追加消耗",
            "order": 76,
        },
    },
)
async def yanzhantai(
    *, user_id: str, message: str, message_context, manager, **_
) -> None:
    await _dispatch(
        "炼阵", user_id, str(message or "").strip(), message_context.request_id, manager
    )


async def _dispatch(
    facility: str, user_id: str, query: str, request_id: str, manager
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
                    raise ValueError("百炼堂需要指定器律")
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
                    raise ValueError("丹鼎阁需要指定丹方")
                value = await feature.craft(
                    facility, user_id, request_id, source, identifier
                )
                await manager.send(reply.completed(feature.copy(), value))
                return
            if parts[0] in _ALCHEMY_CATEGORIES:
                page = int(parts[1]) if len(parts) == 2 else 1
                value = await feature.page(facility, user_id, source, parts[0], page)
                await manager.send(reply.page(feature.copy(), value))
                return
            value = await feature.preview(facility, user_id, source, " ".join(parts))
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
            if len(parts) < 2:
                raise ValueError("演阵台炼阵需要指定阵法和品级")
            identifier, grade = parts[:2]
            investments = _investments(parts[2:])
            value = await feature.craft(
                facility, user_id, request_id, source, identifier, grade, investments
            )
            await manager.send(reply.completed(feature.copy(), value))
            return
        if len(parts) < 2:
            raise ValueError("演阵台审材需要指定阵法和品级")
        identifier, grade = parts[:2]
        investments = _investments(parts[2:])
        value = await feature.preview(
            facility, user_id, source, identifier, grade, investments
        )
        await manager.send(reply.preview(feature.copy(), value))
    except (SectFacilityFeatureError, ValueError) as exc:
        await manager.send(reply.error(feature.copy(), str(exc)))


def _source(query: str) -> tuple[str, list[str]]:
    parts = query.split()
    if parts and parts[0] in _SOURCES:
        return parts[0], parts[1:]
    return "个人", parts


def _investments(values: list[str]):
    if not values:
        return None
    if len(values) != 3 or any(not value.isdigit() for value in values):
        raise ValueError("圣品阵法投入必须依次填写兽宝、灵矿、灵植数量")
    return {"兽宝": int(values[0]), "灵矿": int(values[1]), "灵植": int(values[2])}


__all__ = []
