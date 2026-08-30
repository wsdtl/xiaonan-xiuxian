"""地点专属讨伐命令。"""

from __future__ import annotations

from game.app import current_game_services
from game.features.taofa import RaidFeatureError
from message import M

from ...command import GameCommand, HelpSpec
from ...presentation import duration, natural_deadline


def _error(feature, message):
    return M.document().section(feature.text("错误", "标题"), icon="notice").line(message).build()


@GameCommand.fullmatch(scope="专属", cmd="开始讨伐", aliases=("讨伐",), guard_rule="自主空闲且可行动", help=HelpSpec(category="行动", summary="在当前北方城池发起讨伐", usage=("开始讨伐", "讨伐"), side_effect="预先锁定敌方编组并进入讨伐中", order=36))
async def start_raid(*, user_id: str, message_context, manager, **_) -> None:
    feature = current_game_services().features.taofa
    try:
        value = await feature.start(user_id, message_context.request_id)
        await manager.send(M.document().header(feature.text("开始", "标题")).section(value.location_name, icon="combat").row((feature.text("开始", "参与用户"), value.participant_count), (feature.text("开始", "敌方编组"), value.enemy_group_count)).field(feature.text("开始", "结束时间"), natural_deadline(value.ends_at)).line(feature.text("开始", "说明")).build())
    except RaidFeatureError as exc:
        await manager.send(_error(feature, str(exc)))


@GameCommand.fullmatch(scope="专属", cmd="讨伐战况", aliases=("查看讨伐战况", "讨况"), guard_rule="已创建", help=HelpSpec(category="行动", summary="查看讨伐剩余时间和首领血段", usage=("讨伐战况", "查看讨伐战况", "讨况"), side_effect="只读查询", order=37))
async def raid_progress(*, user_id: str, manager, **_) -> None:
    feature = current_game_services().features.taofa
    try:
        value = await feature.progress(user_id)
        await manager.send(M.document().header(feature.text("进度", "标题")).section(value.location_name, icon="status").row((feature.text("进度", "剩余时间"), duration(value.remaining_seconds)), (feature.text("进度", "首领血段"), f"{value.boss_phase}/{value.boss_phases}")).line(feature.text("进度", "已结束") if value.ended else feature.text("进度", "进行中")).build())
    except RaidFeatureError as exc:
        await manager.send(_error(feature, str(exc)))


@GameCommand.fullmatch(scope="专属", cmd="讨伐结束", aliases=("结算讨伐", "讨伐结算", "结束讨伐", "讨结"), guard_rule="已创建", metadata={"hosting": {"activity": "讨伐", "phase": "end"}}, help=HelpSpec(category="行动", summary="讨伐结束后结算奖励", usage=("讨伐结束", "结算讨伐", "讨伐结算", "结束讨伐", "讨结"), side_effect="发放奖励并释放讨伐状态", order=38))
async def raid_settle(*, user_id: str, message_context, manager, **_) -> None:
    feature = current_game_services().features.taofa
    try:
        value = await feature.settle(user_id, message_context.request_id)
        await manager.send(M.document().header(feature.text("结算", "标题")).section(value.location_name, icon="status").field(feature.text("结算", "结果"), feature.result_label(value.winner)).field(feature.text("结算", "战败敌人"), value.defeated_enemies).line(feature.reward_note(value.winner)).build())
    except RaidFeatureError as exc:
        await manager.send(_error(feature, str(exc)))


__all__ = []
