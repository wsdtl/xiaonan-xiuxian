"""玩家通用切磋命令。"""

from __future__ import annotations

from game.app import current_game_services
from game.features.qiecuo import DuelError, DuelStartCommand
from message import M

from ...command import GameCommand, HelpSpec
from ...presentation import natural_deadline, sentence


@GameCommand.command(
    scope="通用",
    cmd="切磋",
    guard_rule="自主空闲或休息且可行动",
    help=HelpSpec(
        category="战斗",
        summary="向附近玩家及其同行编组发起切磋",
        usage=("切磋 玩家编号或姓名",),
        side_effect="发送切磋邀约，不立即改变正式资源",
        order=80,
    ),
)
async def start(*, user_id: str, message: str, message_context, manager, **_) -> None:
    feature = current_game_services().features.qiecuo
    try:
        target = await feature.resolve_target(user_id, message)
        target_name = await feature.target_name(target)
        value = await feature.start(
            DuelStartCommand(user_id, target, message_context.request_id)
        )
        await manager.send(
            M.document()
            .header(feature.text("发起", "标题"))
            .section("邀约内容", icon="combat")
            .line(feature.text("发起", "说明", 目标=target_name))
            .line(
                feature.text(
                    "发起",
                    "双方",
                    我方人数=len(value.user_participants),
                    对方人数=len(value.target_participants),
                )
            )
            .field("有效时间", natural_deadline(value.expires_at))
            .build()
        )
    except (DuelError, ValueError) as exc:
        await manager.send(
            M.document()
            .section(feature.text("错误", "标题"), icon="notice")
            .line(sentence(str(exc)))
            .build()
        )


@GameCommand.command(
    scope="通用",
    cmd="接受切磋",
    guard_rule="自主空闲或休息且可行动",
    help=HelpSpec(
        category="战斗",
        summary="接受附近玩家发来的切磋邀约",
        usage=("接受切磋",),
        side_effect="执行一次不影响正式资源的切磋并生成战报",
        order=81,
    ),
)
async def accept(*, user_id: str, message_context, manager, **_) -> None:
    feature = current_game_services().features.qiecuo
    try:
        value = await feature.accept(user_id, message_context.request_id)
        challenger_name = await feature.target_name(value.user_participants[0])
        target_name = await feature.target_name(value.target_participants[0])
        await manager.send(
            M.document()
            .header(feature.text("结果", "标题"))
            .section("战果", icon="combat")
            .line(
                feature.text(
                    "结果",
                    "胜方",
                    胜方=feature.winner_label(
                        value.winner, challenger_name, target_name
                    ),
                )
            )
            .line(
                feature.text(
                    "结果",
                    "规模",
                    发起方=challenger_name,
                    发起方人数=len(value.user_participants),
                    目标方=target_name,
                    目标方人数=len(value.target_participants),
                )
            )
            .line(
                feature.text(
                    "结果",
                    "数据",
                    行动数=value.actions,
                    事件数=value.events,
                )
            )
            .build()
        )
    except (DuelError, ValueError) as exc:
        await manager.send(
            M.document()
            .section(feature.text("错误", "标题"), icon="notice")
            .line(sentence(str(exc)))
            .build()
        )


@GameCommand.command(
    scope="通用",
    cmd="拒绝切磋",
    guard_rule="自主空闲或休息",
    help=HelpSpec(
        category="战斗",
        summary="拒绝待处理的切磋邀约",
        usage=("拒绝切磋",),
        side_effect="清除待处理邀约",
        order=82,
    ),
)
async def reject(*, user_id: str, message_context, manager, **_) -> None:
    feature = current_game_services().features.qiecuo
    try:
        await feature.reject(user_id, message_context.request_id)
        await manager.send(M.document().header("切磋邀约已拒绝").build())
    except (DuelError, ValueError) as exc:
        await manager.send(
            M.document()
            .section(feature.text("错误", "标题"), icon="notice")
            .line(str(exc))
            .build()
        )
