"""战前状态的强度对照：给每枚战丹 / 每条会动的伤势量一个"带它的人在镜像对局里的胜率"。

`强度对照.py` 只吃构筑卡（走 `CombatBuildRef`），而战丹与长期伤势走的是
`CombatantSpec.prepared_statuses`，那条路上一直没有量法——`战前状态对照.py` 判的是
**相等**（一个哈希），回答"变了没有"，不回答"变强还是变弱"。本工具补这一格。

做法：两侧装同一张陪练卡、同一套属性，**只有左侧带这件战前状态**，跑若干种子，报左侧胜率：

    胜率 ≈ 0.5  中性（对局结果由陪练卡与种子决定）
    胜率 > 0.5  这件东西是**增益**（战丹该在这边）
    胜率 < 0.5  这件东西是**负担**（长期伤势该在这边）

`无状态对照` 是同配置两侧都不带状态的那一组，把它的胜率当零点，逐件报相对零点的偏移。

    .venv/Scripts/python.exe -X utf8 tools/战前状态强度对照.py --报告 _前.json
    # 改完数据再跑一次，对着上一次的 --报告 看增量
    .venv/Scripts/python.exe -X utf8 tools/战前状态强度对照.py --基准 _前.json

**退出码：0 = 正常，2 = 有抛错。**
"""

from __future__ import annotations

import argparse
import asyncio
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from game.app import build_game_services  # noqa: E402
from game.core.combat.contracts import (  # noqa: E402
    CombatBuildRef,
    CombatantSpec,
    CombatRequest,
    CombatStatusSpec,
)

#: 陪练卡与属性跟 `战前状态对照.py` 取同一套，好让两份读数对得上。
CARD = "400541"
ATTRS = {
    "血气上限": 1200, "精神上限": 400, "攻击": 150, "防御": 60, "速度": 110,
    "命中率": 100, "闪避率": 5, "暴击率": 20, "抗暴率": 5, "暴击伤害": 150,
    #: 伤害加成是加成口径，基准 100 = 不增不减；写 0 等于把伤害乘成 0。
    "格挡率": 10, "破格率": 5, "格挡减伤": 30, "伤害加成": 100, "伤害减免": 0,
}
SEED = 20260911


def specs(root: pathlib.Path, core) -> list[tuple[str, CombatStatusSpec | None]]:
    """产出 (标签, 战前状态)；`基础档战丹`（没有监听）也带上，它靠纯属性起作用。"""

    out: list[tuple[str, CombatStatusSpec | None]] = []
    for path in sorted(root.glob("物品/炼丹/内容/丹药/战丹/*.json")):
        for entry in json.loads(path.read_text(encoding="utf-8")):
            medicine = core.medicine.battle(entry["编号"], "01")
            out.append((f"丹:{entry['编号']}", core.medicine.prepared_status(medicine)))
    injuries = root / "角色" / "内容" / "伤势.json"
    if injuries.exists():
        for entry in json.loads(injuries.read_text(encoding="utf-8")):
            raw = entry.get("战斗状态") or {}
            out.append((f"伤:{entry['编号']}", CombatStatusSpec(
                name=entry["名称"], category=raw["类别"],
                remaining_actions=raw["剩余行动"], duration_unit=raw["持续单位"],
                modifiers=tuple((str(k), float(v)) for k, v in (raw.get("属性") or {}).items()),
                tags=tuple(raw.get("标签") or ()),
                listeners=tuple(dict(node) for node in raw.get("监听") or ()),
                source=entry["编号"], source_name=entry["名称"],
                action_limits=tuple(raw.get("行动限制") or ()),
            )))
    return out


def side(pid: str, prepared: CombatStatusSpec | None) -> CombatantSpec:
    statuses = () if prepared is None else (prepared,)
    return CombatantSpec(
        id=pid, name=pid, attributes=dict(ATTRS),
        build=(CombatBuildRef("功法", CARD, instance_id=f"{pid}:{CARD}", born_order=0),),
        prepared_statuses=statuses,
    )


def win_rate(core, prepared: CombatStatusSpec | None, rounds: int) -> tuple[float, float]:
    """带件方的胜率。

    镜像对局**先手必胜**（两侧同卡同属性时，左方先动就赢），直接量左侧胜率会把读数全压到
    1.0 附近、没有分辨力。所以同一个种子打两场：一场件在左、一场件在右，只数"带件方赢"，
    先手优势自然抵消，中性点回到 0.5。
    """

    wins = 0.0
    actions = 0.0
    for seed in range(rounds):
        for item_left in (True, False):
            left = side("L", prepared) if item_left else side("L", None)
            right = side("R", None) if item_left else side("R", prepared)
            result = asyncio.run(core.combat.execute(CombatRequest(
                left_team=(left,), right_team=(right,),
                seed=SEED + seed, action_limit=60,
            )))
            bearer_won = (result.winner_side == "left") if item_left else (result.winner_side == "right")
            wins += 1.0 if bearer_won else 0.0
            actions += float(result.actions or 0)
    return round(wins / (rounds * 2), 4), round(actions / (rounds * 2), 2)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--对局数", type=int, default=8, help="每件的种子数")
    parser.add_argument("--报告", default="", help="把结果写到这个 json")
    parser.add_argument("--基准", default="", help="与上一次的 --报告 对比增量")
    parser.add_argument("--数据", default=str(ROOT / "data"))
    parser.add_argument("--只报", default="", help="只量标签里含这个字串的（如 伤: / 丹:）")
    args = parser.parse_args()

    root = pathlib.Path(args.数据).resolve()
    core = build_game_services(data_dir=root).core
    neutral, neutral_actions = win_rate(core, None, args.对局数)
    print(f"无状态对照：胜率 {neutral} · 平均行动 {neutral_actions} · 每件 {args.对局数} 种子")

    table: dict[str, dict[str, float]] = {}
    failures: list[str] = []
    for label, prepared in specs(root, core):
        if args.只报 and args.只报 not in label:
            continue
        try:
            rate, actions = win_rate(core, prepared, args.对局数)
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{label}: {type(exc).__name__}: {exc}")
            continue
        table[label] = {"胜率": rate, "偏移": round(rate - neutral, 4), "平均行动": actions}
    core.database.close()

    groups: dict[str, list[float]] = {}
    for label, row in table.items():
        groups.setdefault(label.split(":", 1)[0], []).append(row["胜率"])
    print(f"{len(table)} 件 · 抛错 {len(failures)}")
    for key, values in sorted(groups.items()):
        print(f"   {key}：{len(values)} 件 · 平均胜率 {round(sum(values) / len(values), 4)}"
              f" · 最低 {min(values)} · 最高 {max(values)}")
    for line in failures[:5]:
        print("   抛错 " + line)

    if args.基准:
        base = json.loads(pathlib.Path(args.基准).read_text(encoding="utf-8"))
        base_table = base.get("明细", {})
        print(f"对照 {args.基准}（{len(base_table)} 件）")
        moved = [(label, base_table[label]["胜率"], row["胜率"]) for label, row in table.items()
                 if label in base_table and base_table[label]["胜率"] != row["胜率"]]
        print(f"   胜率有变化的 {len(moved)} 件" + ("" if not moved else "："))
        for label, was, now in sorted(moved, key=lambda item: item[1] - item[2])[:40]:
            print(f"     {label}: {was} -> {now}（{round(now - was, 4):+}）")

    if args.报告:
        pathlib.Path(args.报告).write_text(
            json.dumps({"无状态对照": neutral, "明细": table, "抛错": failures},
                       ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"结果写入 {args.报告}")
    return 2 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
