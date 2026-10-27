"""地点专属阵法浏览与炼阵命令。"""

from __future__ import annotations

from game.app import current_game_services
from game.features.lianzhen import FormationChoiceError, FormationCraftFeatureError
from game.features.presentation import ItemRefError, parse_item_ref

from ...command import GameCommand
from . import reply
from ...reply_composer import send_game_reply
from launch.adapter import MessageContext
from typing import Any

def _grade_prefix(feature: Any, value: str) -> str:
    """按核心口径受理品级的三种写法，吐全名（黄品……）。

    三种写法（黄品／黄／01）的受理归阵法玩法；命令层只转交，不再自己去问资产核心。
    """

    return feature.grade_prefix(value)


def _split_prefix(feature: Any, head: str) -> tuple[str, str]:
    """把「品级阵法名」拆成（品级写法, 阵法名）。

    品级按**从长到短**试：先试前 2 字（圣品），再试前 1 字（圣），最后试前 2 位（01）；
    认不出就当作没有品级前缀（阵法名本身→玩法层按名字查）。
    """

    for length in (2, 1):
        if len(head) > length:
            candidate = head[:length]
            try:
                _grade_prefix(feature, candidate)
                return candidate, head[length:]
            except Exception:  # noqa: BLE001 - 认不出就继续试下一种长度
                continue
    return "", head


def _request(
    message: str, usage: str
) -> tuple[str, str, dict[str, int] | None]:
    # 正规写法：品级阵法名（连写），后面可跟三个投入数（兽宝 灵矿 灵植）。
    # 旧写法「名称 品级 [三个数]」一并受理，照顾老习惯。
    # 扩展位（花括号）**只用于存储**，不接受手打——挑选靠候选点选。
    parts = str(message or "").strip().split()
    feature = current_game_services().features.lianzhen
    # 按钮发来的是**统一存储语法**（一个词，形如 05<阵法编号>{兽宝=…}）——先按它解析。
    # 它同样能吃掉「品级编号+阵法编号」与「品级名+阵法名」这两种一个词的写法。
    if len(parts) == 1 and parts[0]:
        try:
            ref = parse_item_ref(parts[0])
        except ItemRefError:
            ref = None
        if ref is not None and (ref.grade or ref.item):
            try:
                grade = _grade_prefix(feature, ref.grade or "01")
            except Exception:  # noqa: BLE001 - 品级不认识就回落人打语法，由它给同一句用法提示
                grade = ""
            if grade:
                investments = None
                if ref.extra:
                    investments = {str(name): int(str(amount)) for name, amount in ref.extra}
                return ref.item, grade, investments
    try:
        if len(parts) in {2, 5}:  # 旧：名称 品级 [三个数]
            identifier, grade_word, tail = parts[0], parts[1], parts[2:]
        elif len(parts) in {1, 4}:  # 新：品级阵法名 [三个数]
            prefix, identifier = _split_prefix(feature, parts[0])
            # 省略品级就默认黄品（口径：没写品级默认黄品；无品级物品才只有物品名）。
            grade_word, tail = prefix or "黄品", parts[1:]
        else:
            raise ValueError(usage)
        grade = _grade_prefix(feature, grade_word)
    except Exception as exc:  # noqa: BLE001 - 品级不认识时仍然给玩家同一句用法提示
        raise ValueError(usage) from exc
    investments = None
    if tail:
        if grade != "圣品":
            raise ValueError(
                "黄品、玄品、地品、天品按固定配方炼制，不能追加兽宝、灵矿、灵植三数；"
                "圣品才可追加"
            )
        values = tuple(int(value) for value in tail)
        if any(value < 1 for value in values):
            raise ValueError("圣品三相投入必须是正整数")
        investments = dict(zip(("兽宝", "灵矿", "灵植"), values, strict=True))
    return identifier, grade, investments


@GameCommand.command(
    cmd="阵法审查",
    metadata={
        "scope": "专属",
        "guard_rule": "空闲或活动中",
        "help": {
            "category": "炼制",
            "summary": "查看可炼阵法，或审看一座阵法的三相投入",
            "usage": (
                "阵法审查",
                "阵法审查 2",
                "阵法审查 黄品叠翠盘根阵",
                "阵法审查 圣品叠翠盘根阵 100 200 300",
            ),
            "side_effect": "只审材，不消耗材料",
            "order": 65,
        },
    },
)
async def inspect_formation(user_id: str, message: str, manager: Any) -> None:
    feature = current_game_services().features.lianzhen
    query = str(message or "").strip()
    try:
        if not query or query.isdecimal():
            page = int(query) if query else 1
            value = await feature.overview(user_id, page)
            await send_game_reply(
                reply.overview(feature.copy(), value, feature.overview_actions(value))
            )
            return
        identifier, grade, investments = _request(
        query, reply.text(feature.copy(), "错误", "阵法审查格式")
    )
        value = await feature.preview(user_id, identifier, grade, investments)
        await send_game_reply(
            reply.preview(feature.copy(), value, feature.preview_actions(value))
        )
    except FormationChoiceError as exc:
        await send_game_reply(reply.choose(feature.copy(), exc, command="阵法审查"))
    except (FormationCraftFeatureError, ValueError) as exc:
        await send_game_reply(reply.error(feature.copy(), str(exc), feature.format_actions(), command="阵法审查"))


@GameCommand.command(
    cmd="炼阵",
    metadata={
        "scope": "专属",
        "guard_rule": "空闲或活动中",
        "help": {
            "category": "炼制",
            "summary": "把三相材料炼成一份一次性阵法",
            "usage": ("炼阵 黄品叠翠盘根阵", "炼阵 圣品叠翠盘根阵 100 200 300"),
            "side_effect": "消耗兽宝、灵矿和灵植，把阵法收入阵藏",
            "order": 66,
        },
    },
)
async def commit_formation(user_id: str, message: str, message_context: MessageContext, manager: Any) -> None:
    feature = current_game_services().features.lianzhen
    try:
        identifier, grade, investments = _request(
        message, reply.text(feature.copy(), "错误", "炼阵格式")
    )
        value = await feature.form(
            user_id, message_context.request_id, identifier, grade, investments
        )
        await send_game_reply(
            reply.completed(feature.copy(), value, feature.completed_actions())
        )
    except FormationChoiceError as exc:
        await send_game_reply(reply.choose(feature.copy(), exc, command="炼阵"))
    except (FormationCraftFeatureError, ValueError) as exc:
        await send_game_reply(reply.error(feature.copy(), str(exc), feature.format_actions(), command="炼阵"))


__all__ = []
