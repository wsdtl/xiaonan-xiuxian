"""阵法的终局对照：把每个阵法（每个品级）放进一场真实战斗，做成可比对的摘要。

## 为什么需要它

`tools/语料对照.py` 跑构筑、`tools/战前状态对照.py` 跑战丹与伤势、
`tools/战场环境对照.py` 跑战场环境——**阵法两边都不在**。实测全仓 `tools/` 下
没有任何一处构造 `CombatFormationSpec`：46 个阵法、8 位阵师、4 个品级，以及
`阵法展开 / 阵法轮转后 / 阵法冲击后 / 阵法崩解后` 四个事件，行为上一直是零覆盖。

数据侧由 `tools/阵势/**` 与架构审查兜，但「阵法能不能真的进战斗」只有跑一遍才知道。

## 判据

跑两段，因为**两种布阵方式覆盖的代码完全不同**：

1. **只给左方布阵**（每阵法 × 每品级）：测轮转与冲击——冲击打的是对方修士。
   这条路径**永远不会**消耗阵基承载（没有对方阵基可打），实测 184/184 轮转、0 崩解。
2. **双方各布一阵**（阵一对阵二）：阵基承载只在**冲击对方阵基**时才掉，
   归零即崩解。所以崩解这条路径只有这一段能覆盖——实测黄/黄互崩。

两段的摘要收：阵况（`capacity / remaining_capacity / impact / nodes / rotations /
collapsed`）、行动数、双方终局血气。

另外报一行体检：**有多少阵法真的轮转过 / 崩解过**。阵法完全不生效时（例如装配入口
写错、品级表取空）会全部停在同一状态，那是比逐条差异更早的警报。

## 用法

```powershell
.venv/Scripts/python.exe -X utf8 tools/阵法对照.py          # 与入库基准对照
.venv/Scripts/python.exe -X utf8 tools/阵法对照.py --写基准  # 更新基准
```

**退出码约定（与另四条语料通道一致）：0 = 一致，1 = 有差异，2 = 有抛错或基准缺失。**
"""

from __future__ import annotations

import argparse
import asyncio
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
for _path in (str(ROOT), str(ROOT / "tools")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from game.app import build_game_services  # noqa: E402
from game.core.combat.contracts import (  # noqa: E402
    CombatBuildRef,
    CombatFormationSpec,
    CombatantSpec,
    CombatRequest,
)

DEFAULT_BASELINE = ROOT / "tools" / "基准" / "阵法摘要.json"

#: 陪练卡：自带主动与被动的功法，两侧都装，好让阵法的冲击与轮转有机会发生。
CARD = "400541"
SEED = 20260915

#: 行动上限与双方属性都刻意拉长战斗：阵法按**行动周期**轮转（`_formation_base_cycle`
#: × 阶段倍率 ÷ 传导），战斗三五下就结束的话一次都转不到，摘要就只剩「阵法展开」。
#: 实测同一阵法：短战斗 0 轮转 0 冲击；长战斗 4 轮转 4 冲击。
ACTION_LIMIT = 220

#: 阵品。`status()` 报固定四品；`圣` 是无上品，不逐个跑。
GRADES = ("黄", "玄", "地", "天")

ATTRS = {
    "血气上限": 9000, "精神上限": 2000, "攻击": 50, "防御": 200, "速度": 100,
    "命中率": 100, "闪避率": 0, "暴击率": 0, "抗暴率": 0, "暴击伤害": 150,
    #: 伤害加成是加成口径，基准 100 = 不增不减；写 0 等于把伤害乘成 0。
    "格挡率": 0, "破格率": 0, "格挡减伤": 0, "伤害加成": 100, "伤害减免": 50,
}

#: 对阵段：双方各布一阵。承载只在冲击对方阵基时掉，所以崩解只有这段能覆盖。
#: 阵对挑两个代表（黄品承载最小、最易崩）；血气放小让战斗短一点，两个阵基都撞得到。
VERSUS = ("530001", "530002")
VERSUS_GRADE = "黄"
VERSUS_LIMIT = 300
VERSUS_ATTRS = {
    "血气上限": 9000, "精神上限": 3000, "攻击": 50, "防御": 100, "速度": 100,
    "命中率": 100, "闪避率": 0, "暴击率": 0, "抗暴率": 0, "暴击伤害": 150,
    #: 伤害加成是加成口径，基准 100 = 不增不减；写 0 等于把伤害乘成 0。
    "格挡率": 0, "破格率": 0, "格挡减伤": 0, "伤害加成": 100, "伤害减免": 30,
}


def _loop(core, *, left_formation, right_formation, attrs, limit, seed):
    """跑一场战斗并返回（结果, 抛错文本）。"""

    def side(pid: str) -> CombatantSpec:
        return CombatantSpec(
            id=pid,
            name=pid,
            attributes=dict(attrs),
            build=(
                CombatBuildRef("功法", CARD, instance_id=f"{pid}:{CARD}", born_order=0),
            ),
        )

    return asyncio.run(core.combat.execute(CombatRequest(
        left_team=(side("L"),),
        right_team=(side("R"),),
        seed=seed,
        action_limit=limit,
        left_formation=left_formation,
        right_formation=right_formation,
    )))


def _row(result) -> dict[str, object]:
    """把一场战斗收成摘要行。"""

    def shape_of(side: int):
        for item in result.formations:
            if item.side == side:
                return [
                    round(float(item.capacity), 3),
                    round(float(item.remaining_capacity), 3),
                    round(float(item.impact), 3),
                    item.nodes,
                    item.rotations,
                    item.collapsed,
                ]
        return None

    return {
        "左阵": shape_of(0),
        "右阵": shape_of(1),
        "行动数": result.actions,
        "左血": round(float(result.left.health), 3),
        "右血": round(float(result.right.health), 3),
    }


def digest(root: pathlib.Path) -> tuple[dict[str, object], list[str]]:
    """返回（摘要, 抛错清单）。抛错要记账：当成空结果会掩盖最该看见的回归。"""

    services = build_game_services(data_dir=root)
    core = services.core
    formation = services.core.formation
    # `formations()` 返回定义对象，按编号排序（对象本身不可比）。
    formations = sorted(item.formation_id for item in formation.formations())
    summary: dict[str, object] = {}
    failures: list[str] = []
    try:
        # 第一段：只给左方布阵，逐个阵法 × 逐个品级 —— 测轮转与冲击。
        for formation_id in formations:
            for grade in GRADES:
                key = f"单阵/{formation_id}/{grade}"
                try:
                    result = _loop(
                        core,
                        left_formation=CombatFormationSpec(
                            formation_id=formation_id, grade=grade, position=0),
                        right_formation=None,
                        attrs=ATTRS,
                        limit=ACTION_LIMIT,
                        seed=SEED,
                    )
                except Exception as exc:  # noqa: BLE001
                    failures.append(f"{key}：{type(exc).__name__}: {exc}")
                    continue
                summary[key] = _row(result)

        # 第二段：双方各布一阵 —— 阵基承载只在冲击对方阵基时才掉，崩解只有这里能覆盖。
        for index, first in enumerate(VERSUS):
            for second in VERSUS:
                key = f"对阵/{first}/{second}"
                try:
                    result = _loop(
                        core,
                        left_formation=CombatFormationSpec(
                            formation_id=first, grade=VERSUS_GRADE, position=0),
                        right_formation=CombatFormationSpec(
                            formation_id=second, grade=VERSUS_GRADE, position=0),
                        attrs=VERSUS_ATTRS,
                        limit=VERSUS_LIMIT,
                        seed=SEED + 1,
                    )
                except Exception as exc:  # noqa: BLE001
                    failures.append(f"{key}：{type(exc).__name__}: {exc}")
                    continue
                summary[key] = _row(result)
    finally:
        core.database.close()
    return summary, failures


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--基准", default=str(DEFAULT_BASELINE), help="入库基准摘要")
    parser.add_argument("--写基准", action="store_true", help="把当前摘要写进 --基准")
    parser.add_argument("--数据", default=str(ROOT / "data"), help="要跑的数据目录")
    args = parser.parse_args()

    root = pathlib.Path(args.数据)
    summary, failures = digest(root)
    print(f"{len(summary)} 条（单阵 {len(summary) - len(VERSUS) ** 2}"
          f" + 对阵 {len(VERSUS) ** 2}），抛错 {len(failures)} 个；数据目录 {root}")
    for failure in failures[:10]:
        print(f"  {failure}")

    rotated = [k for k, v in summary.items()
               if (v.get("左阵") or [None, None, None, None, 0])[4]]
    collapsed = [k for k, v in summary.items()
                 if (v.get("左阵") or [None] * 6)[5] or (v.get("右阵") or [None] * 6)[5]]
    print(f"  阵基轮转过的：{len(rotated)} / {len(summary)}"
          + ("（一个都没轮转，阵法很可能完全没生效）" if summary and not rotated else ""))
    print(f"  有阵基崩解的：{len(collapsed)} / {len(summary)}"
          + ("（对阵段一条都没崩，崩解路径未被覆盖）"
             if summary and not collapsed else ""))

    baseline = pathlib.Path(args.基准)
    if args.写基准:
        if failures:
            print("有阵法抛错，拒绝写基准——否则会把坏状态固化成判据。")
            return 2
        baseline.parent.mkdir(parents=True, exist_ok=True)
        baseline.write_text(
            json.dumps(summary, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            + "\n",
            encoding="utf-8",
        )
        print(f"已写入 {baseline}")
        return 0

    if not baseline.is_file():
        print(f"基准不存在：{baseline}；先跑一次 --写基准")
        return 2
    try:
        expected = json.loads(baseline.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"基准无法读取：{exc}")
        return 2
    if not isinstance(expected, dict):
        print(f"基准结构不对：{baseline} 应为对象")
        return 2

    changed = sorted(
        key for key in summary.keys() & expected.keys() if summary[key] != expected[key]
    )
    added = sorted(summary.keys() - expected.keys())
    missing = sorted(expected.keys() - summary.keys())
    same = len(summary.keys() & expected.keys()) - len(changed)
    print(
        f"对照 {baseline}（{len(expected)} 条）："
        f"一致 {same} / {len(summary)} · 差异 {len(changed)}"
        f" · 新增 {len(added)} · 缺失 {len(missing)}"
    )
    for key in changed[:20]:
        before = json.dumps(expected[key], ensure_ascii=False, sort_keys=True)
        after = json.dumps(summary[key], ensure_ascii=False, sort_keys=True)
        print(f"  [差异] {key}")
        print(f"      -{before[:150]}")
        print(f"      +{after[:150]}")
    if len(changed) > 20:
        print(f"  …… 其余 {len(changed) - 20} 条差异从略")
    for key in added[:10]:
        print(f"  [新增] {key}")
    for key in missing[:10]:
        print(f"  [缺失] {key}")

    if failures:
        return 2
    return 1 if (changed or added or missing) else 0


if __name__ == "__main__":
    raise SystemExit(main())
