"""宗门战通用命令。"""

from __future__ import annotations

from game.app import current_game_services
from game.features.zongmen_zhan import SectWarError

from ...command import GameCommand, HelpSpec
from . import reply


def _feature():
    return current_game_services().features.zongmen_zhan


@GameCommand.command(
    scope="通用",
    cmd="宗门约战",
    aliases=("约战",),
    guard_rule="宗门战发起",
    help=HelpSpec(
        category="战斗",
        summary="向另一宗门发出战书",
        usage=("宗门约战 宗门名 灵石数量", "约战 宗门名 灵石数量"),
        side_effect="发起时扣除本宗押注；撤回、拒绝或过期会原额退回",
        order=1,
    ),
)
async def challenge(*, user_id, message, message_context, manager, **_) -> None:
    parts = str(message or "").split()
    try:
        if len(parts) != 2 or not parts[1].isdecimal() or int(parts[1]) < 1:
            raise ValueError
        value = await _feature().challenge(
            user_id, parts[0], int(parts[1]), message_context.request_id
        )
        await manager.send(reply.view(_feature(), value))
    except ValueError:
        await manager.send(reply.error(_feature().text("错误", "challenge_format")))
    except SectWarError as exc:
        await manager.send(reply.error(_feature().error(exc)))


@GameCommand.command(
    scope="通用",
    cmd="接战",
    aliases=("应战", "接受宗门战"),
    guard_rule="宗门战待命",
    help=HelpSpec(
        category="战斗",
        summary="接受本宗当前战书",
        usage=("接战", "应战", "接受宗门战"),
        order=2,
    ),
)
async def accept(*, user_id, message_context, manager, **_) -> None:
    await _run(manager, _feature().accept(user_id, message_context.request_id))


@GameCommand.command(
    scope="通用",
    cmd="拒战",
    aliases=("拒绝宗门战",),
    guard_rule="宗门战待命",
    help=HelpSpec(
        category="战斗",
        summary="拒绝本宗当前战书",
        usage=("拒战", "拒绝宗门战"),
        order=3,
    ),
)
async def reject(*, user_id, message_context, manager, **_) -> None:
    await _run(manager, _feature().reject(user_id, message_context.request_id))


@GameCommand.command(
    scope="通用",
    cmd="撤战",
    aliases=("撤回战书", "撤回宗门战书"),
    guard_rule="宗门战待命",
    help=HelpSpec(
        category="战斗",
        summary="撤回本宗发出的战书",
        usage=("撤战", "撤回战书", "撤回宗门战书"),
        order=4,
    ),
)
async def withdraw(*, user_id, message_context, manager, **_) -> None:
    await _run(manager, _feature().withdraw(user_id, message_context.request_id))


@GameCommand.command(
    scope="通用",
    cmd="锁阵",
    aliases=("锁定宗门战阵容",),
    guard_rule="宗门战待命",
    help=HelpSpec(
        category="战斗",
        summary="锁定宗门同行和可选宗门阵法",
        usage=(
            "锁定宗门战阵容",
            "锁定宗门战阵容 万珍殿阵法条目",
            "锁阵 万珍殿阵法条目",
        ),
        side_effect="所选宗门阵法在正式开战时消耗",
        order=5,
    ),
)
async def lock(*, user_id, message, message_context, manager, **_) -> None:
    await _run(
        manager,
        _feature().lock(
            user_id, message_context.request_id, str(message or "").strip()
        ),
    )


@GameCommand.command(
    scope="通用",
    cmd="解阵",
    aliases=("解除宗门战阵容",),
    guard_rule="宗门战操作",
    help=HelpSpec(
        category="战斗",
        summary="解除本宗已锁定阵容",
        usage=("解阵", "解除宗门战阵容"),
        order=6,
    ),
)
async def unlock(*, user_id, message_context, manager, **_) -> None:
    await _run(manager, _feature().unlock(user_id, message_context.request_id))


@GameCommand.command(
    scope="通用",
    cmd="开战",
    aliases=("开启宗门战",),
    guard_rule="宗门战操作",
    help=HelpSpec(
        category="战斗",
        summary="双方锁阵后开始正式宗门战",
        usage=("开启宗门战", "开战"),
        side_effect="预计算战斗并消耗阵法、战丹和实际使用的恢复丹",
        order=7,
    ),
)
async def start(*, user_id, message_context, manager, **_) -> None:
    await _run(manager, _feature().start(user_id, message_context.request_id))


@GameCommand.command(
    scope="通用",
    cmd="停战",
    aliases=("取消宗门战", "取消战斗"),
    guard_rule="宗门战操作",
    help=HelpSpec(
        category="战斗",
        summary="开战前取消当前宗门战",
        usage=("取消宗门战", "取消战斗"),
        side_effect="退回双方押注并释放已经锁定的参战者",
        order=8,
    ),
)
async def cancel(*, user_id, message_context, manager, **_) -> None:
    await _run(manager, _feature().cancel(user_id, message_context.request_id))


@GameCommand.command(
    scope="通用",
    cmd="战况",
    aliases=("查看宗门战况", "宗门战况"),
    guard_rule="已创建",
    help=HelpSpec(
        category="战斗",
        summary="查看并在到时后自动结算当前宗门战",
        usage=("查看宗门战况", "查看宗门战况 战书编号", "宗门战况 战书编号"),
        order=9,
    ),
)
async def current(*, user_id, message, message_context, manager, **_) -> None:
    try:
        war_id = str(message or "").strip()
        value = (
            await _feature().view(user_id, war_id)
            if war_id
            else await _feature().current(user_id, message_context.request_id)
        )
        await manager.send(reply.view(_feature(), value))
    except SectWarError as exc:
        await manager.send(reply.error(_feature().error(exc)))


@GameCommand.command(
    scope="通用",
    cmd="战录",
    aliases=("查看宗门战记录", "宗门战记录"),
    guard_rule="已创建",
    help=HelpSpec(
        category="战斗",
        summary="分页查看本宗历史宗门战",
        usage=("查看宗门战记录", "查看宗门战记录 2", "宗门战记录 2"),
        order=10,
    ),
)
async def history(*, user_id, message, manager, **_) -> None:
    try:
        raw = str(message or "").strip()
        if raw and (not raw.isdecimal() or int(raw) < 1):
            raise ValueError
        await manager.send(
            reply.history(_feature(), await _feature().history(user_id, int(raw or 1)))
        )
    except ValueError:
        await manager.send(reply.error(_feature().text("错误", "history_format")))
    except SectWarError as exc:
        await manager.send(reply.error(_feature().error(exc)))


async def _run(manager, operation) -> None:
    try:
        await manager.send(reply.view(_feature(), await operation))
    except SectWarError as exc:
        await manager.send(reply.error(_feature().error(exc)))


__all__ = []
