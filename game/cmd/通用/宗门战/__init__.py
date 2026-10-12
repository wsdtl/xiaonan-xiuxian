"""宗门战通用命令。"""

from __future__ import annotations

from collections.abc import Awaitable
from game.features.zongmen_zhan import SectWarView, SectWarFeature, SectWarError


from game.app import current_game_services

from ...command import GameCommand
from . import reply
from launch.adapter import MessageContext
from typing import Any


def _feature() -> SectWarFeature:
    return current_game_services().features.zongmen_zhan


@GameCommand.command(
    cmd=("宗门约战", "约战"),
    metadata={
        "scope": "通用",
        "guard_rule": "宗门战发起",
        "help": {
            "category": "战斗",
            "summary": "向另一宗门发出战书",
            "usage": ("宗门约战 太素坊 1000", "宗门约战 宗门名 灵石数量", "约战 宗门名 灵石数量"),
            "side_effect": "发起时扣除本宗押注；撤回、拒绝或过期会原额退回；正式结算按九成——胜方取彩池九成、平局各返九成，一成是损耗",
            "order": 1,
        },
    },
)
async def challenge(user_id: str, message: str, message_context: MessageContext, manager: Any) -> None:
    parts = str(message or "").split()
    try:
        if len(parts) != 2 or not parts[1].isdecimal() or int(parts[1]) < 1:
            raise ValueError
        value = await _feature().challenge(
            user_id, parts[0], int(parts[1]), message_context.request_id
        )
        await manager.send(reply.view(_feature(), value))
    except ValueError:
        await manager.send(reply.error(_feature(), _feature().text("错误", "约战写法"), _feature().format_actions("约战格式")))
    except SectWarError as exc:
        await manager.send(reply.error(_feature(), _feature().error(exc), _feature().format_actions("约战格式")))


@GameCommand.command(
    cmd=("接战", "应战", "接受宗门战"),
    metadata={
        "scope": "通用",
        "guard_rule": "宗门战待命",
        "help": {
            "category": "战斗",
            "summary": "接受本宗当前战书",
        "side_effect": "接受后进入备战；双方锁阵后到点自动开战并结算",
            "usage": ("接战", "应战", "接受宗门战"),
            "order": 2,
        },
    },
)
async def accept(user_id: str, message_context: MessageContext, manager: Any) -> None:
    await _run(manager, _feature().accept(user_id, message_context.request_id))


@GameCommand.command(
    cmd=("拒战", "拒绝宗门战"),
    metadata={
        "scope": "通用",
        "guard_rule": "宗门战待命",
        "help": {
            "category": "战斗",
            "summary": "拒绝本宗当前战书",
        "side_effect": "拒绝后战书作废",
            "usage": ("拒战", "拒绝宗门战"),
            "order": 3,
        },
    },
)
async def reject(user_id: str, message_context: MessageContext, manager: Any) -> None:
    await _run(manager, _feature().reject(user_id, message_context.request_id))


@GameCommand.command(
    cmd=("撤战", "撤回战书", "撤回宗门战书"),
    metadata={
        "scope": "通用",
        "guard_rule": "宗门战待命",
        "help": {
            "category": "战斗",
            "summary": "撤回本宗发出的战书",
        "side_effect": "撤回后战书作废",
            "usage": ("撤战", "撤回战书", "撤回宗门战书"),
            "order": 4,
        },
    },
)
async def withdraw(user_id: str, message_context: MessageContext, manager: Any) -> None:
    await _run(manager, _feature().withdraw(user_id, message_context.request_id))


def _has_cjk(value: str) -> bool:
    """含中文就是「名字写法」；只有数字与冒号就是「id 写法」（原汁原味）。"""

    return any('\u4e00' <= ch <= '\u9fff' for ch in value)


async def _formation_key(user_id: str, wanted: str) -> str:
    """把玩家写的阵法换成万珍殿条目键——与「发放万珍殿」共用同一份解析（玩法层 `resolve_vault_entry`）。

    认不出就原样返回，由核心按展示数据的话回绝；玩法层的回绝（多条说不清）翻成宗门战自己的错误类型。
    """
    text = str(wanted or '').strip()
    if not text:
        return text
    try:
        return await current_game_services().features.zongmen_wanzhen.resolve_vault_entry(
            user_id, text
        )
    except SectWarError:
        raise
    except Exception as exc:  # noqa: BLE001 - 命令层不认核心/玩法异常类型，翻成自己这层的话
        raise SectWarError(str(exc)) from exc

@GameCommand.command(
    cmd=("锁阵", "锁定宗门战阵容"),
    metadata={
        "scope": "通用",
        "guard_rule": "宗门战待命",
        "help": {
            "category": "战斗",
            "summary": "锁定宗门同行和可选宗门阵法",
            "usage": (
                "锁定宗门战阵容",
                "锁定宗门战阵容 阵法名[灵宝名]",
                "锁阵 阵法名[灵宝名]",
            ),
            "side_effect": "所选宗门阵法在正式开战时消耗",
            "order": 5,
        },
    },
)

async def lock(user_id: str, message: str, message_context: MessageContext, manager: Any) -> None:
    services = current_game_services()
    raw = str(message or "").strip()
    try:
        key = await _formation_key(user_id, raw) if raw else ""
    except SectWarError as exc:
        await manager.send(
            reply.error(_feature(), _feature().error(exc), _feature().format_actions("约战格式"))
        )
        return
    await _run(
        manager,
        _feature().lock(user_id, message_context.request_id, key),
    )


@GameCommand.command(
    cmd=("解阵", "解除宗门战阵容"),
    metadata={
        "scope": "通用",
        "guard_rule": "宗门战操作",
        "help": {
            "category": "战斗",
            "summary": "解除本宗已锁定阵容",
        "side_effect": "解除后可以重新锁阵",
            "usage": ("解阵", "解除宗门战阵容"),
            "order": 6,
        },
    },
)
async def unlock(user_id: str, message_context: MessageContext, manager: Any) -> None:
    await _run(manager, _feature().unlock(user_id, message_context.request_id))


@GameCommand.command(
    cmd=("开战", "开启宗门战"),
    metadata={
        "scope": "通用",
        "guard_rule": "宗门战操作",
        "help": {
            "category": "战斗",
            "summary": "双方锁阵后开始正式宗门战",
            "usage": ("开启宗门战", "开战"),
            "side_effect": "预计算战斗并消耗阵法、战丹和实际使用的恢复丹",
            "order": 7,
        },
    },
)
async def start(user_id: str, message_context: MessageContext, manager: Any) -> None:
    await _run(manager, _feature().start(user_id, message_context.request_id))


@GameCommand.command(
    cmd=("停战", "取消宗门战", "取消战斗"),
    metadata={
        "scope": "通用",
        "guard_rule": "宗门战操作",
        "help": {
            "category": "战斗",
            "summary": "开战前取消当前宗门战",
            "usage": ("取消宗门战", "取消战斗"),
            "side_effect": "退回双方押注并释放已经锁定的参战者",
            "order": 8,
        },
    },
)
async def cancel(user_id: str, message_context: MessageContext, manager: Any) -> None:
    await _run(manager, _feature().cancel(user_id, message_context.request_id))


@GameCommand.command(
    cmd=("战况", "查看宗门战况", "宗门战况"),
    metadata={
        "scope": "通用",
        "guard_rule": "已创建",
        "help": {
            "category": "战斗",
            "summary": "查看并在到时后自动结算当前宗门战",
        "side_effect": "查看只读；但到点后再看会自动结算并记下战果",
            "usage": ("查看宗门战况", "查看宗门战况 战书编号", "宗门战况 战书编号"),
            "order": 9,
        },
    },
)
async def current(user_id: str, message: str, message_context: MessageContext, manager: Any) -> None:
    try:
        war_id = str(message or "").strip()
        value = (
            await _feature().view(user_id, war_id)
            if war_id
            else await _feature().current(user_id, message_context.request_id)
        )
        await manager.send(reply.view(_feature(), value))
    except SectWarError as exc:
        await manager.send(reply.error(_feature(), _feature().error(exc), _feature().format_actions("约战格式")))


@GameCommand.command(
    cmd=("战录", "查看宗门战记录", "宗门战记录"),
    metadata={
        "scope": "通用",
        "guard_rule": "已创建",
        "help": {
            "category": "战斗",
            "summary": "分页查看本宗历史宗门战",
        "side_effect": "只读，按页查看历史战报",
            "usage": ("查看宗门战记录", "查看宗门战记录 2", "宗门战记录 2"),
            "order": 10,
        },
    },
)
async def history(user_id: str, message: str, manager: Any) -> None:
    try:
        raw = str(message or "").strip()
        if raw and (not raw.isdecimal() or int(raw) < 1):
            raise ValueError
        await manager.send(
            reply.history(_feature(), await _feature().history(user_id, int(raw or 1)))
        )
    except ValueError:
        await manager.send(reply.error(_feature(), _feature().text("错误", "战况写法"), _feature().format_actions("战录格式")))
    except SectWarError as exc:
        await manager.send(reply.error(_feature(), _feature().error(exc), _feature().format_actions("约战格式")))


async def _run(manager: Any, operation: Awaitable[SectWarView]) -> None:
    try:
        await manager.send(reply.view(_feature(), await operation))
    except SectWarError as exc:
        await manager.send(reply.error(_feature(), _feature().error(exc), _feature().format_actions("约战格式")))


__all__ = []
