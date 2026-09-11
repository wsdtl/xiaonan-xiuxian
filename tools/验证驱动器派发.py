"""验证 QQ webhook、QQ WebSocket 与 Local 驱动器共用派发逻辑的行为契约。

用于抽取 `shared_dispatch.py` 前后逐字节比对。覆盖：

- `_execution_plan`：block 规则截取语义（含边界组合）；
- `_short_text`：压缩、按长度截断、空白归一、空值；
- `_callback_wrapper`：注册项绑定与调用次数、参数透传。

只依赖驱动器规则数据类与已注册的公开函数，不进入游戏层。
"""

from __future__ import annotations

import json
import pathlib
import sys

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from launch.adapter.local.handler import LocalCommandMatch, LocalCommandRule  # noqa: E402
from launch.adapter.local.handler import LocalEventHandler  # noqa: E402
from launch.adapter.qq_protocol.rules import QqCommandMatch, QqCommandRule  # noqa: E402
from launch.adapter.qq_wh import QqEventHandler  # noqa: E402
from launch.adapter.qq_ws import QqWsEventHandler  # noqa: E402


def _noop() -> None:
    """占位业务回调。"""


def _plan_cases(rule_cls, match_cls) -> list[tuple[str, list]]:
    """构造覆盖 block 语义的用例。"""

    def make(priority: int, block: bool):
        return match_cls(
            rule=rule_cls(func=_noop, priority=priority, block=block, order=priority),
            command=f"c{priority}",
            message="",
        )

    return [
        ("空列表", []),
        ("单个不 block", [make(10, False)]),
        ("单个 block", [make(10, True)]),
        ("先 block 后低优先", [make(10, True), make(5, False)]),
        ("先 block 后同优先", [make(10, True), make(10, False)]),
        ("先 block 后高优先", [make(10, True), make(20, False)]),
        ("多个都不 block", [make(10, False), make(20, False), make(30, False)]),
        ("高优先 block 在前", [make(30, True), make(20, False), make(10, False)]),
        ("中位 block", [make(30, False), make(20, True), make(10, False), make(25, False)]),
        ("重复优先不同 block", [make(5, False), make(5, True), make(5, False)]),
        ("零与负优先", [make(0, False), make(-5, True), make(1, False)]),
    ]


def _text_cases() -> list[object]:
    return [
        "",
        "   ",
        "\n\t ",
        "短",
        "刚好八十" * 20,
        "a" * 79,
        "a" * 80,
        "a" * 81,
        "多处   空白\n\t要归一",
        "中文" * 60,
        None,
        0,
        ["列表", "值"],
    ]


def _wrapper_cases(handler) -> dict[str, object]:
    calls: list[tuple] = []

    def registrar(command, func, priority, block, metadata) -> None:
        calls.append((command, func.__name__, priority, block, dict(metadata or {})))

    def business() -> None:
        """业务回调。"""

    decorator = handler._callback_wrapper(
        ["甲", "乙", "丙"], registrar, 7, True, {"scope": "通用"}
    )
    returned = decorator(business)
    return {
        "calls": calls,
        "returned_is_func": returned is business,
        "returned_name": returned.__name__,
    }


def snapshot(handler, rule_cls, match_cls) -> dict[str, object]:
    plans = {}
    for label, matched in _plan_cases(rule_cls, match_cls):
        planned = handler._execution_plan(matched)
        plans[label] = [item.command for item in planned]
    texts = {repr(value): handler._short_text(value) for value in _text_cases()}
    limited = {str(n): handler._short_text("x" * 200, limit=n) for n in (5, 10, 80, 200)}
    return {
        "plans": plans,
        "texts": texts,
        "limited": limited,
        "wrapper": _wrapper_cases(handler),
    }


def _comparable(snapshot_value: dict[str, object]) -> dict[str, object]:
    """去掉与共享语义无关的驱动器标识后用于跨驱动器比对。"""

    return {key: value for key, value in snapshot_value.items() if key != "name"}


def main() -> int:
    """断言三个驱动器在共享派发逻辑上给出一致且符合契约的结果。

    可选参数 `--dump <路径>` 会把完整快照写成 JSON，供抽取重构前后比对。
    """

    drivers = (
        ("QQ webhook", QqEventHandler, QqCommandRule, QqCommandMatch),
        ("QQ WebSocket", QqWsEventHandler, QqCommandRule, QqCommandMatch),
        ("Local", LocalEventHandler, LocalCommandRule, LocalCommandMatch),
    )
    snapshots = {
        name: {"name": name, **snapshot(handler, rule_cls, match_cls)}
        for name, handler, rule_cls, match_cls in drivers
    }

    if "--dump" in sys.argv:
        out = pathlib.Path(sys.argv[sys.argv.index("--dump") + 1])
        out.write_text(
            json.dumps(snapshots, ensure_ascii=False, indent=1, sort_keys=True),
            encoding="utf-8",
        )
        print(f"已保存 {out}")

    failures: list[str] = []
    baseline_name, baseline = next(iter(snapshots.items()))
    baseline = _comparable(baseline)

    # 1. 共享逻辑必须给出一致结果，否则说明驱动器又各自演化出差异。
    for name, snapshot_value in snapshots.items():
        if name == baseline_name:
            continue
        for key in ("plans", "texts", "limited", "wrapper"):
            if snapshot_value[key] != baseline[key]:
                failures.append(f"{baseline_name} 与 {name} 在 {key} 上结果不一致")

    # 2. 截断符契约：统一使用单字符省略号。
    for name, snapshot_value in snapshots.items():
        texts = snapshot_value["texts"]
        truncated = [v for v in texts.values() if len(v) > 1 and not v.endswith("-")]
        used_ellipsis = any(v.endswith("…") for v in truncated)
        used_three_dots = any(v.endswith("...") for v in truncated)
        if used_three_dots:
            failures.append(f"{name} 的 _short_text 使用了三点省略号")
        elif not used_ellipsis:
            failures.append(f"{name} 的 _short_text 未产出单字符省略号")

    # 3. block 计划语义：block 之后优先级更低的回调必须被截掉。
    for name, snapshot_value in snapshots.items():
        plans = snapshot_value["plans"]
        if plans["先 block 后低优先"] != ["c10"]:
            failures.append(f"{name} 的 block 截取未丢弃低优先回调")
        if plans["先 block 后同优先"] != ["c10", "c10"]:
            failures.append(f"{name} 的 block 截取误丢弃同优先回调")
        if plans["空列表"] != []:
            failures.append(f"{name} 的空输入未返回空计划")

    if failures:
        print(f"驱动器派发契约不成立 {len(failures)} 处：")
        for item in failures:
            print(f"  {item}")
        return 1
    count = len(baseline["plans"]) + len(baseline["texts"]) + len(baseline["limited"])
    print(
        f"驱动器派发契约验证通过：{count} 项输入，"
        f"{len(snapshots)} 个驱动器结果一致（{'、'.join(snapshots)}）"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
