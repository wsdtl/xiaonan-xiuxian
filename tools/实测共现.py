"""实测共现：跑真实战斗，看哪些卡**真的**在同一个事件上同时触发。

`tools/盘点监听顺序.py` 是静态 triage，它只能说「这两张卡存在交集」——先前列出的
721 张待办里绝大部分永远不会相遇（例如 27 张地的 `修改判定`，一场仗只有一个环境）。
这个工具反过来做：跑满构筑对战，在监听执行的那一刻记一笔，按**事件派发实例**分组，
于是能算出真正同场同事件撞过的卡对。顺序只有在这些卡对之间才需要定。

归因按**卡**而不是按单条监听：定序用的 `结算顺序` 本来就是按卡声明的，
而 `优先级` 只在同一张卡内部需要分开排时才用。

    .venv/Scripts/python.exe -X utf8 tools/实测共现.py
    .venv/Scripts/python.exe -X utf8 tools/实测共现.py --构筑数 80 --等级 100
"""

from __future__ import annotations

import argparse
import asyncio
import collections
import dataclasses
import importlib.util
import io
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from game.app import build_game_services  # noqa: E402
from game.core.combat.contracts import (  # noqa: E402
    CombatBuildRef,
    CombatantSpec,
    CombatRequest,
)
from game.core.combat.mechanics import AbilityRuntime  # noqa: E402

_spec = importlib.util.spec_from_file_location("战斗统计", ROOT / "tools" / "战斗统计.py")
统计 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(统计)
_pan = importlib.util.spec_from_file_location("盘点", ROOT / "tools" / "盘点监听顺序.py")
盘点 = importlib.util.module_from_spec(_pan)
_pan.loader.exec_module(盘点)

#: 编号前缀 -> 来源层级名。跨层先后已由 `来源层级` 决定，只有同层才需要定序。
PREFIX_LAYER = {"40": "功法", "41": "真意", "42": "气机", "70": "器律"}


def layer_of(card: str) -> str | None:
    return PREFIX_LAYER.get(card[:2])


def card_traits(root: pathlib.Path):
    """(卡号, 事件) -> {写, 读}。用静态盘点的同一套判据，保证两边口径一致。"""

    traits: dict[tuple[str, str], dict[str, set[str]]] = {}
    for _direction, _path, entry in 盘点.corpus(root):
        card = str(entry.get("编号") or "")
        if not card:
            continue
        found: list[dict] = []
        盘点.listeners(entry, found)
        for node in found:
            writes, reads = 盘点.classify(node)
            body = traits.setdefault((card, str(node["事件"])), {"写": set(), "读": set()})
            body["写"] |= writes
            body["读"] |= reads
    return traits


class Tracer:
    """按**事件派发实例**给监听执行分组。

    `_dispatch_event` 每次调用分配一个序号并压栈，`_run_effects` 记下栈顶序号，
    于是同一次派发里跑过的监听自然分到一组；嵌套派发各归各的组。
    只记监听体的调用，不记技能体内嵌的效果——那两者都是 `_run_effects`，
    所以用「栈顶是不是刚新建的派发」来区分：进入 `_dispatch_event` 后
    第一个 `_run_effects` 才是监听体。
    """

    def __init__(self) -> None:
        self.groups: dict[int, set[tuple[str, str]]] = collections.defaultdict(set)
        self.kinds: dict[int, str] = {}
        self._serial = 0
        self._stack: list[tuple[int, str]] = []

    def dispatch(self, original, mechanics, context, *, kind, source, target, **kwargs):
        self._serial += 1
        serial = self._serial
        self.kinds[serial] = str(kind)
        self._stack.append((serial, kind))
        try:
            return original(mechanics, context, kind=kind, source=source,
                            target=target, **kwargs)
        finally:
            self._stack.pop()

    def run(self, original, mechanics, context, source, target, effects, multiplier, **kwargs):
        if self._stack:
            serial = self._stack[-1][0]
            instance = str(context.current_build_instance or "")
            if ":" in instance:
                owner, card = instance.split(":", 1)
                self.groups[serial].add((owner, card))
        return original(mechanics, context, source, target, effects, multiplier, **kwargs)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--数据", dest="data", default=str(ROOT / "data"))
    parser.add_argument("--报告", dest="report", default="_实测共现.txt")
    parser.add_argument("--等级", dest="等级", type=int, default=100)
    parser.add_argument("--构筑数", dest="构筑数", type=int, default=60)
    parser.add_argument("--上限", dest="limit", type=int, default=60)
    args = parser.parse_args()

    root = pathlib.Path(args.data).resolve()
    traits = card_traits(root)
    attrs = 统计.level_attributes(root, args.等级)
    builds = 统计.full_builds(root, args.构筑数)

    tracer = Tracer()
    _orig_dispatch = AbilityRuntime._dispatch_event
    _orig_run = AbilityRuntime._run_effects

    def dispatch(self, context, *, kind, source, target, **kwargs):
        return tracer.dispatch(_orig_dispatch, self, context, kind=kind,
                               source=source, target=target, **kwargs)

    def run(self, context, source, target, effects, multiplier, **kwargs):
        return tracer.run(_orig_run, self, context, source, target, effects,
                          multiplier, **kwargs)

    AbilityRuntime._dispatch_event = dispatch
    AbilityRuntime._run_effects = run

    core = build_game_services(data_dir=root).core

    def side(pid: str, entries) -> CombatantSpec:
        refs = tuple(
            CombatBuildRef(a, b, instance_id=f"{pid}:{b}", born_order=i)
            for i, (a, b) in enumerate(entries)
        )
        return CombatantSpec(id=pid, name=pid, attributes=dict(attrs), build=refs)

    # (事件, 卡A, 卡B) -> 次数；卡A < 卡B 归一化
    pairs: collections.Counter = collections.Counter()
    interlocks: dict[tuple[str, str, str], set[str]] = {}
    dispatch_kinds: collections.Counter = collections.Counter()
    multi = 0
    total_dispatch = 0
    failures: list[str] = []

    for index, entries in enumerate(builds):
        other = builds[(index + 1) % len(builds)]
        tracer.groups.clear()
        tracer.kinds.clear()
        tracer._serial = 0
        tracer._stack.clear()
        try:
            asyncio.run(core.combat.execute(CombatRequest(
                left_team=(side("L", entries),), right_team=(side("R", other),),
                seed=20260911 + index * 7919, action_limit=args.limit,
            )))
        except Exception as exc:  # noqa: BLE001
            failures.append(f"构筑{index} {type(exc).__name__}: {exc}")
            continue
        for serial, members in tracer.groups.items():
            kind = tracer.kinds.get(serial, "")
            total_dispatch += 1
            dispatch_kinds[kind] += 1
            cards = sorted({card for _owner, card in members})
            if len(cards) < 2:
                continue
            multi += 1
            for i, left in enumerate(cards):
                left_trait = traits.get((left, kind), {"写": set(), "读": set()})
                for right in cards[i + 1:]:
                    right_trait = traits.get((right, kind), {"写": set(), "读": set()})
                    shared = 盘点.interlock(
                        (left_trait["写"], left_trait["读"]),
                        (right_trait["写"], right_trait["读"]),
                    )
                    if shared:
                        pairs[(kind, left, right)] += 1
                        interlocks[(kind, left, right)] = shared

    core.database.close()

    out = io.TextIOWrapper(open(ROOT / args.report, "wb"), encoding="utf-8")
    out.write(f"实测共现：{root}\n")
    out.write(f"{args.等级} 级 · {args.构筑数} 套满构筑（左用第 i 套、右用第 i+1 套）"
              f"· 行动上限 {args.limit}\n")
    out.write(f"抛错 {len(failures)} 场\n")
    out.write(f"事件派发 {total_dispatch} 次，其中同一事件上有 ≥2 张卡参与 {multi} 次\n\n")

    out.write("=" * 100 + "\n")
    out.write("一、真正撞过的顺序敏感卡对（同事件、同派发、有读写交集）\n")
    out.write("=" * 100 + "\n")
    out.write(f"{'次数':>6}  {'事件':<14} 卡对\n")
    for (kind, left, right), count in pairs.most_common(60):
        out.write(f"{count:>6}  {kind:<14} {left} × {right}\n")
    out.write(f"\n卡对种类合计 {len(pairs)}，出现次数合计 {sum(pairs.values())}\n")

    # 跨层卡对已被「来源层级」排好（功法 20 < 器律 30 < 真意 40），不需要定序。
    # 真正要动手的只有同层卡对。
    out.write("\n" + "=" * 100 + "\n")
    out.write("二、**同层**卡对（跨层已被来源层级解决，只有这些需要定序）\n")
    out.write("=" * 100 + "\n")
    same_layer = [
        (count, kind, left, right)
        for (kind, left, right), count in pairs.items()
        if layer_of(left) is not None and layer_of(left) == layer_of(right)
    ]
    same_layer.sort(reverse=True)
    out.write(f"{'次数':>6}  {'事件':<14} {'层':<5} 卡对 / 咬住的量\n")
    for count, kind, left, right in same_layer[:60]:
        keys = "/".join(sorted(interlocks.get((kind, left, right), ())))
        out.write(f"{count:>6}  {kind:<14} {layer_of(left):<5} "
                  f"{left} × {right}   {keys}\n")
    out.write(f"\n同层卡对种类 {len(same_layer)}，"
              f"出现次数合计 {sum(row[0] for row in same_layer)}\n")
    out.write(f"跨层卡对种类 {len(pairs) - len(same_layer)}（不需要动作）\n")

    out.write("\n" + "=" * 100 + "\n")
    out.write("三、参与方最多的几个事件（派发次数）\n")
    out.write("=" * 100 + "\n")
    for kind, count in dispatch_kinds.most_common(20):
        out.write(f"  {count:>7}  {kind}\n")

    if failures:
        out.write("\n抛错明细：\n")
        for line in failures:
            out.write(f"    {line}\n")
    out.write("\n注：共现 ≠ 一定需要定序，但它把候选从「可能共存」收成「真的撞过」。\n")
    out.write("    判先后仍是作者意图；写写冲突尤其如此。\n")
    out.flush()
    print(f"详见 {args.report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
