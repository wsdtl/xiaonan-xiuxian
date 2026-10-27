"""炼阵：总览、只读目录与直接炼阵。"""
from __future__ import annotations

from typing import Any

from game.app import current_game_services
from game.features.lianzhen import FormationChoiceError, FormationCraftFeatureError
from game.features.presentation import ItemRefError, parse_item_ref

from ...command import GameCommand
from ...reply_composer import send_game_reply
from launch.adapter import MessageContext
from . import reply


def _grade_prefix(feature: Any, value: str) -> str:
    return feature.grade_prefix(value)


def _split_prefix(feature: Any, head: str) -> tuple[str, str]:
    for length in (2, 1):
        if len(head) > length:
            candidate = head[:length]
            try:
                _grade_prefix(feature, candidate)
                return candidate, head[length:]
            except Exception:  # noqa: BLE001 - 认不出就继续试下一种长度
                continue
    return "", head


def _request(message: str, usage: str) -> tuple[str, str, dict[str, int] | None, bool]:
    parts = str(message or "").strip().split()
    feature = current_game_services().features.lianzhen
    if len(parts) == 1 and parts[0]:
        try:
            ref = parse_item_ref(parts[0])
        except ItemRefError:
            ref = None
        if ref is not None and (ref.grade or ref.item):
            try:
                grade = _grade_prefix(feature, ref.grade or "01")
            except Exception:  # noqa: BLE001
                grade = ""
            if grade:
                investments = None
                if ref.extra:
                    investments = {str(name): int(str(amount)) for name, amount in ref.extra}
                return ref.item, grade, investments, bool(ref.grade)
    try:
        explicit = False
        if len(parts) in {2, 5}:
            identifier, grade_word, tail = parts[0], parts[1], parts[2:]
            explicit = True
        elif len(parts) in {1, 4}:
            prefix, identifier = _split_prefix(feature, parts[0])
            grade_word, tail = prefix or "黄品", parts[1:]
            explicit = bool(prefix)
        else:
            raise ValueError(usage)
        grade = _grade_prefix(feature, grade_word)
    except Exception as exc:  # noqa: BLE001
        raise ValueError(usage) from exc
    investments = None
    if tail:
        if grade != "圣品":
            raise ValueError("黄品、玄品、地品、天品按固定配方炼制，不能追加兽宝、灵矿、灵植三数；圣品才可追加")
        investments = dict(zip(("兽宝", "灵矿", "灵植"), (int(value) for value in tail), strict=True))
        if any(value < 1 for value in investments.values()):
            raise ValueError("圣品三相投入必须是正整数")
    return identifier, grade, investments, explicit


def _error(feature: Any, message: str, command: str) -> object:
    return reply.error(feature.copy(), message, feature.format_actions(), command=command)


async def _overview(user_id: str, page: int = 1) -> None:
    feature = current_game_services().features.lianzhen
    value = await feature.overview(user_id, page)
    await send_game_reply(reply.overview(feature.copy(), value, feature.overview_actions(value)))


@GameCommand.command(
    cmd="炼阵",
    metadata={
        "scope": "专属",
        "guard_rule": "空闲或活动中",
        "help": {
            "category": "炼制",
            "summary": "查看炼阵总览，或直接炼一座阵法",
            "usage": ("炼阵", "炼阵 黄品叠翠盘根阵", "炼阵 圣品叠翠盘根阵 100 200 300"),
            "side_effect": "写完整阵法且三相材料足时消耗材料并收入阵藏；缺材料只回预览",
            "order": 65,
        },
    },
)
async def formation_root(user_id: str, message: str, message_context: MessageContext, manager: Any) -> None:
    feature = current_game_services().features.lianzhen
    query = str(message or "").strip()
    try:
        if not query:
            await _overview(user_id)
            return
        identifier, grade, investments, explicit = _request(
            query, reply.text(feature.copy(), "错误", "炼阵格式")
        )
        if not explicit:
            await send_game_reply(reply.choose_grade(feature.copy(), identifier))
            return
        preview = await feature.preview(user_id, identifier, grade, investments)
        if preview.can_form:
            value = await feature.form(user_id, message_context.request_id, identifier, grade, investments)
            await send_game_reply(reply.completed(feature.copy(), value, feature.completed_actions()))
        else:
            await send_game_reply(reply.preview(feature.copy(), preview, feature.preview_actions(preview)))
    except FormationChoiceError as exc:
        await send_game_reply(reply.choose(feature.copy(), exc, command="炼阵"))
    except (FormationCraftFeatureError, ValueError) as exc:
        await send_game_reply(_error(feature, str(exc), "炼阵"))


@GameCommand.command(
    cmd="炼阵目录",
    metadata={
        "scope": "专属",
        "guard_rule": "空闲或活动中",
        "help": {
            "category": "炼制",
            "summary": "只读查看可炼阵法目录；不查库存、不炼阵、不消耗",
            "usage": ("炼阵目录", "炼阵目录 2", "炼阵目录 黄品叠翠盘根阵"),
            "side_effect": "目录列表只读；单条详情才查这一条的三相材料，不直接消耗",
            "order": 66,
        },
    },
)
async def formation_catalog(user_id: str, message: str, manager: Any) -> None:
    feature = current_game_services().features.lianzhen
    query = str(message or "").strip()
    try:
        if not query:
            await _overview(user_id)
            return
        if query.isdecimal():
            if int(query) < 1:
                raise ValueError("写法：炼阵目录 [页码]")
            await _overview(user_id, int(query))
            return
        identifier, grade, investments, explicit = _request(
            query, reply.text(feature.copy(), "错误", "炼阵格式")
        )
        if not explicit:
            await send_game_reply(reply.choose_grade(feature.copy(), identifier))
            return
        value = await feature.preview(user_id, identifier, grade, investments)
        await send_game_reply(reply.preview(feature.copy(), value, feature.preview_actions(value)))
    except FormationChoiceError as exc:
        await send_game_reply(reply.choose(feature.copy(), exc, command="炼阵目录"))
    except (FormationCraftFeatureError, ValueError) as exc:
        await send_game_reply(_error(feature, str(exc), "炼阵目录"))


__all__ = []
