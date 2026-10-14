"""命令冷却：同一个人对同一条命令的短时间重复触发，冷却未到就不回应。

设计要点（施工单见 tools/基准/说明.md）：

- **键＝注册期铸造的序号**：与命令名、别名、模块、适配器全都无关。用名字做键会被两种写法击穿
  （同一模块内重复定义同名函数，前一个可能已经注册；以及换别名）。序号在装饰器那一刻生成，天然唯一。
- **value＝(上次放行时刻, 首个命令名)**：名字只用来读日志，不参与判重。
- **进程内内存字典**：重启即清空，这是本能力的前提；多进程部署要换成共享存储。
- **默认不进表**：没设冷却（0 或没值）的命令直接放行，不写字典，所以表自然长不大。
- **守卫用最低优先级**：run_command_guards 是"首个拦截即停"，放最后跑，本守卫的"记时刻"
  就精确等于"最终放行"——被状态守卫或主持守卫拦掉的请求不会吃掉冷却。
"""

from __future__ import annotations

import time
from typing import Any

from loguru import logger

from .command_guard import (
    CommandGuardContext,
    CommandGuardDecision,
    register_command_guard,
    unregister_command_guard,
)

#: 游戏侧塞进 command_metadata 的保留键。
COOLDOWN_FIELD = "冷却秒"
COOLDOWN_KEY_FIELD = "冷却键"
COOLDOWN_NAME_FIELD = "冷却名"

GUARD_NAME = "命令冷却"
#: 最小优先级：数值越小越晚跑，本守卫排最后。
GUARD_PRIORITY = -1000

_windows: dict[str, tuple[float, str]] = {}


def register_command_cooldown_guard() -> None:
    """注册命令冷却守卫（由游戏组合根显式调用，与访问守卫同处）。"""

    register_command_guard(GUARD_NAME, _check, priority=GUARD_PRIORITY)


def unregister_command_cooldown_guard() -> None:
    """随游戏微服务关闭移除冷却守卫（与访问守卫对称）。"""

    unregister_command_guard(GUARD_NAME)


def clear_command_cooldowns() -> None:
    """清空冷却表：测试用，免得用例之间互相污染。"""

    _windows.clear()


def active_cooldowns() -> tuple[tuple[str, str, float], ...]:
    """当前还在窗口内的冷却，供观测与测试断言。"""

    now = time.monotonic()
    return tuple(
        (key, name, now - started) for key, (started, name) in _windows.items()
    )


async def _check(context: CommandGuardContext) -> CommandGuardDecision:
    metadata: dict[str, Any] = context.command_metadata or {}
    key = str(metadata.get(COOLDOWN_KEY_FIELD) or "").strip()
    if not key:
        return CommandGuardDecision.allow()
    raw = metadata.get(COOLDOWN_FIELD)
    if raw in (None, ""):
        return CommandGuardDecision.allow()
    try:
        window = float(raw)
    except (TypeError, ValueError):
        return CommandGuardDecision.allow()
    if window <= 0:
        return CommandGuardDecision.allow()

    now = time.monotonic()
    name = str(metadata.get(COOLDOWN_NAME_FIELD) or key)
    # 冷却按「人 × 命令」算：键必须带上 user_id，否则所有人共用一条冷却（第③条真跑抓到过）。
    table_key = f"{context.user_id}\0{key}"
    last = _windows.get(table_key)
    if last is not None and now - last[0] < window:
        # 冷却中：拦下且不带回复（静默）。
        logger.debug(
            f"命令冷却中：{last[1]} 还剩 {window - (now - last[0]):.1f}s"
            f" user_id={context.user_id}"
        )
        return CommandGuardDecision.block()
    _windows[table_key] = (now, name)
    return CommandGuardDecision.allow()


__all__ = [
    "COOLDOWN_FIELD",
    "COOLDOWN_KEY_FIELD",
    "COOLDOWN_NAME_FIELD",
    "GUARD_NAME",
    "active_cooldowns",
    "clear_command_cooldowns",
    "register_command_cooldown_guard",
    "unregister_command_cooldown_guard",
]
