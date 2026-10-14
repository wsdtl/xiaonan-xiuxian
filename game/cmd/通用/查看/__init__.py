"""查看类命令入口。"""

from __future__ import annotations

from game.app import current_game_services
from game.features.chakan_wupin import ItemInspectionResult
from game.features.daolv_jiejiao import CompanionAccessError
from launch.paths import public_url

from ...command import GameCommand
from . import reply
from .site import router
from typing import Any


@GameCommand.command(
    cmd="查看",
    metadata={
        "scope": "通用",
        "guard_rule": "始终可用",
        "help": {
            "category": "资源",
            "summary": "按编号或名称查看物品、功法、道侣等详细资料",
            "usage": ("查看 100001", "查看 编号", "查看 名称"),
            "side_effect": "只读查询，不改变人物、背包或世界状态",
            "order": 10,
        },
    },
)
async def inspect_entity(user_id: str, message: str, manager: Any) -> None:
    query = " ".join(str(message or "").split())
    if not query:
        await manager.send(reply.missing_query())
        return

    #: 敌人走 30 段专属分派：它们是命名实体池，不在 item_catalog 的编号索引里。
    if query in current_game_services().features.chakan_wupin.enemy_identifiers():
        feature = current_game_services().features.chakan_wupin
        detail = feature.inspect_enemy(query)
        result = (
            ItemInspectionResult(query, detail=detail, mask_text=feature.mask_text())
            if detail
            else ItemInspectionResult(query)
        )
        await manager.send(reply.inspection(result, public_url("baike")))
        return
    #: 6 位、50 开头 = 我自己名下的道侣（实例化道侣），不要求在附近——就是原位置组件那条按编号看名下道侣的路子。
    weizhi = current_game_services().features.weizhi
    if len(query) == 6 and query.isdigit() and query[:2] == "50":
        companion_view = await weizhi.inspect_companion(user_id, query)
        if companion_view is not None:
            await manager.send(
                reply.companion(
                    weizhi.copy(),
                    companion_view,
                    weizhi.nearby_cultivator_actions(1, False),
                )
            )
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
    #: 静态数据实体（物品/功法/道侣模板/敌人）优先于动态在场者，认不出才当"附近的人"。
    if result.detail is None:
        person = await weizhi.inspect_cultivator(user_id, query)
        if person is not None:
            await manager.send(
                reply.cultivator(
                    weizhi.copy(), person, weizhi.nearby_cultivator_actions(1, False)
                )
            )
            return
    await manager.send(reply.inspection(result, public_url("baike"), actions))


__all__ = ["router"]
