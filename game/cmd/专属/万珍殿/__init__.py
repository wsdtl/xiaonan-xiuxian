"""宗门洞天专属万珍殿命令。"""

from __future__ import annotations

from game.app import current_game_services
from game.features.presentation import (
    ItemRef,
    ItemRefError,
    format_item_ref,
    parse_item_ref,
)
from game.features.zongmen_wanzhen import WanzhenFeatureError

from ...command import GameCommand
from . import reply
from .site import router
from launch.adapter import MessageContext
from typing import Any

_CATEGORIES = frozenset({"丹药", "真意", "气机", "器律", "阵法"})


async def _formation_key(feature: Any, user_id: str, wanted: str, qualifier: str) -> str:
    """把玩家写的阵法换成个人阵藏条目键。

    命令层只做**协议解析**：方括号是给阵法名用的，里面写数字（阵法编号）当场回绝；
    匹配、候选与回绝文案全部由玩法层的 `resolve_formation_entry` 给出——
    命令层不再自己筛资产快照、也不再自己查灵宝名。
    """

    query = str(wanted or '').strip()
    bracket = ""
    if query.endswith("]") and "[" in query:
        head, _, bracket = query[:-1].partition("[")
        head, bracket = head.strip(), bracket.strip()
        if head.isdecimal():
            copy = feature.copy()
            copy_text = getattr(copy, "text", copy)
            raise WanzhenFeatureError(
                str(copy_text.get("阵法编号别带方括号") or "阵法编号别带方括号").format(
                    number=head
                )
            )
        query = head
    if bracket and not qualifier:
        qualifier = bracket
    # 方括号里的灵宝走显式的 treasure 槽：别与品级抢同一个位置（旧的 qualifier 继续接品级）。
    return await feature.resolve_formation_entry(user_id, query, qualifier, treasure=bracket)


@GameCommand.command(
    cmd="万珍殿",
    metadata={
        "scope": "专属",
        "guard_rule": "已创建",
        "help": {
            "category": "宗门",
            "summary": "在本宗洞天分类查看宗门成品",
            "usage": ("万珍殿", "万珍殿 丹药", "万珍殿 阵法 2"),
            "side_effect": "只读查询；成品由宗主统一发放",
            "order": 82,
        },
    },
)
async def show_wanzhen(user_id: str, message: str, manager: Any) -> None:
    feature = current_game_services().features.zongmen_wanzhen
    parts = str(message or "").split()
    try:
        if len(parts) > 2:
            raise WanzhenFeatureError("格式：万珍殿 [类别] [页码]")
        category = parts[0] if parts else "全部"
        page_number = _positive(parts[1], "万珍殿页码") if len(parts) == 2 else 1
        value = await feature.page(user_id, category, page_number)
        await manager.send(
            reply.page(feature.copy(), value, feature.page_actions(value))
        )
    except WanzhenFeatureError as exc:
        await manager.send(reply.error(feature.copy(), str(exc)))


@GameCommand.command(
    cmd=("捐珍", "捐入万珍殿"),
    metadata={
        "scope": "专属",
        "guard_rule": "自主空闲或休息",
        "help": {
            "category": "宗门",
            "summary": "将个人成品存入本宗万珍殿",
            "usage": (
                "捐入万珍殿 丹药 01100005 3",
                "捐入万珍殿 器律 编号或名称 数量",
                # help 优先用编号（委托方 2026-10-15 口径）；实在没有编号的才用中文名。
                "捐入万珍殿 阵法 阵法名[灵宝名]",
                "捐入万珍殿 阵法 01530001",
            ),
            "side_effect": "扣除个人成品，计入万珍殿；阵法每次存入一座",
            "order": 83,
        },
    },
)
async def donate_wanzhen(user_id: str, message: str, message_context: MessageContext, manager: Any) -> None:
    feature = current_game_services().features.zongmen_wanzhen
    parts = str(message or "").split()
    try:
        if not parts or parts[0] not in _CATEGORIES:
            raise WanzhenFeatureError("格式：捐入万珍殿 类别 内容 ...")
        category = parts[0]
        if category == "阵法" and 2 <= len(parts) <= 3:
            # 新写法：<品级><阵法名>[灵宝]；旧写法 <阵法名> [品级] 仍受理。
            name_word = parts[1]
            old_qualifier = parts[2] if len(parts) == 3 else ""
            try:
                ref = parse_item_ref(name_word)
            except ItemRefError:
                ref = None
            if ref is not None and (ref.grade or ref.treasure):
                # 仍走 _formation_key（它负责「阵法编号别带方括号」那道拒绝），
                # 方括号里的灵宝由它用 treasure 槽转发，不跟品级抢位置。
                wanted = format_item_ref(ItemRef(item=ref.item, treasure=ref.treasure))
                identifier = await _formation_key(
                    feature, user_id, wanted, ref.grade or old_qualifier
                )
            else:
                identifier = await _formation_key(feature, user_id, name_word, old_qualifier)
            grade_or_key, quantity = identifier, 1
        elif category == "器律" and len(parts) == 3:
            identifier, grade_or_key, quantity = (
                parts[1],
                "",
                _positive(parts[2], "数量"),
            )
        elif category in {"丹药", "真意", "气机"} and len(parts) in {3, 4}:
            if len(parts) == 4:
                identifier, grade_or_key = parts[1], parts[2]
            else:
                ref = parse_item_ref(parts[1])
                identifier, grade_or_key = ref.item, ref.grade
            quantity = _positive(parts[-1], "数量")
        else:
            raise WanzhenFeatureError("万珍殿存入参数与类别不匹配")
        value = await feature.donate(
            user_id,
            message_context.request_id,
            category,
            identifier,
            grade_or_key,
            quantity,
        )
        await manager.send(reply.transferred(feature.copy(), value))
    except WanzhenFeatureError as exc:
        await manager.send(reply.error(feature.copy(), str(exc)))


@GameCommand.command(
    cmd=("发珍", "发放万珍殿"),
    metadata={
        "scope": "专属",
        "guard_rule": "自主空闲或休息",
        "help": {
            "category": "宗门",
            "summary": "由宗主或长老向本宗成员发放万珍殿成品",
            "usage": (
                "发放万珍殿 云中鹤 01100005", "发放万珍殿 角色名 珍物名[灵宝名]",
                "发放万珍殿 角色名或编号 珍物名[灵宝名] 数量",
            ),
            "side_effect": "扣除宗门成品，计入目标成员的个人藏库",
            "order": 84,
        },
    },
)
async def grant_wanzhen(user_id: str, message: str, message_context: MessageContext, manager: Any) -> None:
    feature = current_game_services().features.zongmen_wanzhen
    parts = str(message or "").split()
    try:
        if len(parts) not in {2, 3}:
            raise WanzhenFeatureError("格式：发放万珍殿 目标 条目编号 [数量]")
        quantity = _positive(parts[2], "数量") if len(parts) == 3 else 1
        # 玩家写法 → 条目键（含中文走名字写法、纯编号按内容编号、整条键原汁原味）；
        # 认不出就原样交给核心，由核心用展示数据的话回绝。
        entry_key = await feature.resolve_vault_entry(user_id, parts[1])
        value = await feature.grant(
            user_id,
            message_context.request_id,
            parts[0],
            entry_key,
            quantity,
        )
        await manager.send(reply.transferred(feature.copy(), value))
    except WanzhenFeatureError as exc:
        await manager.send(reply.error(feature.copy(), str(exc)))


def _positive(value: str, label: str) -> int:
    if not value.isdecimal() or int(value) < 1:
        raise WanzhenFeatureError(f"{label}必须是正整数")
    return int(value)


__all__ = ["router"]
