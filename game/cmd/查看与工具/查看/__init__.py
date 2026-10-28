"""查看类命令入口。"""

from __future__ import annotations

from game.app import current_game_services
from game.features.chakan_juese import CharacterOverviewError
from game.features.chakan_wupin import ItemInspectionResult
from game.features.daolv_jiejiao import CompanionAccessError
from game.features.daolv_peiyang import CompanionCultivationFeatureError
from launch.paths import public_url

from ...command import GameCommand
from . import reply
from .site import router
from ...reply_composer import send_game_reply
from typing import Any


@GameCommand.command(
    cmd="查看",
    metadata={
        "scope": "通用",
        "guard_rule": "始终可用",
        "help": {
            "category": "查看与工具",
            "summary": "按编号或名称查看物品、功法、道侣等详细资料",
            "usage": ("查看 清心散", "查看 编号", "查看 名称"),
            "side_effect": "只读查询，不改变人物、背包或世界状态",
            "order": 10,
        },
    },
)
async def inspect_entity(user_id: str, message: str, manager: Any) -> None:
    query = " ".join(str(message or "").split())
    if not query:
        await send_game_reply(reply.missing_query())
        return

    if query in {"自己", "我"}:
        try:
            overview = await current_game_services().features.chakan_juese.inspect(user_id)
        except CharacterOverviewError:
            await send_game_reply(reply.overview_error(), title="查看 自己")
            return
        xuemai = current_game_services().features.xuemai
        dna = await xuemai.dna(user_id)
        await send_game_reply(
            reply.overview(
                overview,
                overview.altitude_unit,
                dna=dna,
                bloodlines=xuemai.bloodlines(dna),
            ),
            title="查看 自己",
        )
        return

    #: 敌人走 30 段专属分派：它们是命名实体池，不在 item_catalog 的编号索引里。
    if query in current_game_services().features.chakan_wupin.enemy_identifiers():
        feature = current_game_services().features.chakan_wupin
        detail = feature.inspect_enemy(query)
        result = (
            ItemInspectionResult(
                query,
                detail=detail,
                related_details=feature.related_details(detail),
                mask_text=feature.mask_text(),
            )
            if detail
            else ItemInspectionResult(query)
        )
        await send_game_reply(
            reply.inspection(result, public_url("baike")),
            title=f"查看 {detail.name}" if detail else None,
        )
        return
    #: 6 位、50 开头 = 我自己名下的道侣（实例化道侣），不要求在附近——就是原位置组件那条按编号看名下道侣的路子。
    weizhi = current_game_services().features.weizhi
    if len(query) == 6 and query.isdigit() and query[:2] == "50":
        if await _send_companion_page(user_id, query, weizhi):
            return

    result = await current_game_services().features.chakan_wupin.inspect(query, user_id)
    actions: tuple[Any, ...] = ()
    detail = result.detail
    if detail is not None and detail.section == "道侣":
        # 道侣卡的联动按钮由道侣互动玩法按目标给（交谈/赠予/邀约/暂别，条件也由展示数据定）。
        # 互动那边要玩家人在道侣所在地；查看是只读且随处可用，所以取不到就退回「没有按钮」，
        # 不能让它把查看整条命令弄成报错。
        companions = current_game_services().features.daolv_jiejiao
        try:
            view = await companions.inspect(user_id, detail.item_id)
        except CompanionAccessError:
            view = None
        if view is not None:
            actions = companions.actions("查看", view)
        #: 已经结交的道侣：名字/编号都能进完整个人页；未结交仍是静态模板。
        if await _send_companion_page(user_id, detail.item_id, weizhi):
            return
    #: 静态数据实体（物品/功法/道侣模板/敌人）优先于动态在场者，认不出才当"附近的人"。
    if result.detail is None:
        person = await weizhi.inspect_cultivator(user_id, query)
        if person is not None:
            await send_game_reply(
                reply.cultivator(
                    weizhi.copy(), person, weizhi.nearby_cultivator_actions(1, False)
                ),
                title=f"查看 {person.name}",
            )
            return
    await send_game_reply(
        reply.inspection(result, public_url("baike"), actions),
        title=f"查看 {detail.name}" if detail is not None else None,
    )


async def _send_companion_page(user_id: str, companion_id: str, weizhi: Any) -> bool:
    """已结交道侣的完整个人页；没有实例就退回静态模板。"""

    view = await weizhi.inspect_companion(user_id, companion_id)
    if view is None:
        return False
    services = current_game_services()
    try:
        cultivation = await services.features.daolv_peiyang.inspect(user_id)
    except CompanionCultivationFeatureError:
        cultivation = None
    actions: tuple[Any, ...] = ()
    try:
        interaction = await services.features.daolv_jiejiao.inspect(user_id, companion_id)
    except CompanionAccessError:
        interaction = None
    if interaction is not None:
        actions = services.features.daolv_jiejiao.actions("查看", interaction)
    await send_game_reply(
        reply.companion(
            weizhi.copy(),
            view,
            actions or weizhi.nearby_cultivator_actions(1, False),
            cultivation,
        ),
        title=f"查看 {view.name}",
    )
    return True


__all__ = ["router"]
