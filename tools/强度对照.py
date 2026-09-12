"""强度对照：量一小批构筑卡的胜负，用来给「改写批」报强度漂移。

`交叉对局对照.py` 判的是**相等**（一个哈希），它回答「变了没有」，不回答「变强还是变弱」。
本工具补这一格：给一批卡，各对三名固定对手各打若干局，报胜/负/平与平均行动，
并可与上一次的 `--基准` 结果对比出**增量**。

    .venv/Scripts/python.exe -X utf8 tools/强度对照.py --卡集 _授权集.json --报告 _后.json
    .venv/Scripts/python.exe -X utf8 tools/强度对照.py --卡集 _授权集.json --基准 _后.json

卡集文件取 `交叉对局对照.py --差异名单` 写出的格式（读 `差异卡` 字段），
也接受 `{"功法:400001": ...}` 这类按卡片的字典，或一个纯列表。

**退出码：0 = 正常，2 = 卡集为空或有抛错。**
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
    CombatRequest,
    CombatantSpec,
)

ATTRS = {
    "血气上限": 1200, "精神上限": 400, "攻击": 150, "防御": 60, "速度": 110,
    "命中率": 100, "闪避率": 5, "暴击率": 20, "抗暴率": 5, "暴击伤害": 150,
    "格挡率": 10, "破格率": 5, "格挡减伤": 30, "伤害加成": 0, "伤害减免": 0,
}
ATTRS_R = {
    **ATTRS,
    "血气上限": 1800, "精神上限": 620, "攻击": 90, "防御": 130, "速度": 80,
    "格挡率": 25, "暴击率": 5,
}
OPPONENTS = (("功法", "400503"), ("真意", "410275"), ("器律", "700001"))


def load_cards(path: pathlib.Path) -> list[str]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        for key in ("差异卡", "卡", "授权卡"):
            if key in raw:
                return [str(item) for item in raw[key]]
        if raw and all(isinstance(value, list) for value in raw.values()):
            # 也吃 `换源恢复.py --授权集` 的格式：{"data/战斗/内容/真意/真意-绝境.json": ["410129", …]}
            # 体裁取**文件名前缀**（`器律-时序.json` → 器律）。按目录倒数第二段取会在器律上错：
            # 器律在 `data/炼器/内容/` 下，那一段是「内容」，于是器律卡被记成 `内容:700001`。
            cards = [f"{pathlib.Path(name).stem.split('-')[0]}:{cid}"
                     for name, ids in raw.items() for cid in ids]
            return sorted(set(cards))
        return [str(key) for key in raw]
    return [str(item) for item in raw]


def spec(pid: str, card: str, *, right: bool = False) -> CombatantSpec:
    section, cid = card.split(":", 1)
    return CombatantSpec(
        id=pid, name=pid, attributes=dict(ATTRS_R if right else ATTRS),
        build=(CombatBuildRef(section, cid, instance_id=f"{pid}:{cid}", born_order=0),),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--卡集", required=True, help="卡片清单文件（见模块文档）")
    parser.add_argument("--对局数", type=int, default=24, help="每张卡对每名对手的种子数")
    parser.add_argument("--报告", default="", help="把结果写到这个 json")
    parser.add_argument("--基准", default="", help="与上一次的 --报告 对比增量")
    parser.add_argument("--数据", default=str(ROOT / "data"))
    args = parser.parse_args()

    cards = load_cards(pathlib.Path(args.卡集))
    if not cards:
        print("卡集为空，没什么可量的。")
        return 2

    core = build_game_services(data_dir=pathlib.Path(args.数据).resolve()).core
    table: dict[str, dict[str, float]] = {}
    failures: list[str] = []
    for card in cards:
        stat = {"局": 0.0, "胜": 0.0, "负": 0.0, "平": 0.0, "回合": 0.0}
        for opponent in OPPONENTS:
            other = f"{opponent[0]}:{opponent[1]}"
            for seed in range(args.对局数):
                stat["局"] += 1
                try:
                    result = asyncio.run(core.combat.execute(CombatRequest(
                        left_team=(spec("L", card),),
                        right_team=(spec("R", other, right=True),),
                        seed=20260911 + seed, action_limit=60,
                    )))
                    outcome = result.winner_side
                    stat["胜" if outcome == "left" else "负" if outcome == "right" else "平"] += 1
                    stat["回合"] += float(result.actions or 0)
                except Exception as exc:  # noqa: BLE001
                    failures.append(f"{card} vs {other} seed={seed}: {type(exc).__name__}: {exc}")
        stat["胜率"] = round(stat["胜"] / stat["局"], 4)
        stat["平均行动"] = round(stat["回合"] / stat["局"], 2)
        table[card] = stat
    core.database.close()

    total = {key: round(sum(row[key] for row in table.values()), 2)
             for key in ("局", "胜", "负", "平")}
    total["胜率"] = round(total["胜"] / total["局"], 4) if total["局"] else 0.0
    print(f"{len(table)} 张卡 · 共 {int(total['局'])} 局 · 胜率 {total['胜率']} · 抛错 {len(failures)}")
    for line in failures[:5]:
        print("  抛错 " + line)

    if args.基准:
        base = json.loads(pathlib.Path(args.基准).read_text(encoding="utf-8"))
        print(f"对照 {args.基准}（胜率 {base.get('合计', {}).get('胜率')}）")
        for card in sorted(table):
            was, now = base.get("卡片", {}).get(card), table[card]
            if not was:
                print(f"  {card}: 基准里没有，跳过")
                continue
            delta = round(now["胜率"] - was["胜率"], 4)
            flag = "" if abs(delta) < 0.05 else "  <- 变化较大"
            print(f"  {card}: 胜率 {was['胜率']} -> {now['胜率']}（{delta:+}）"
                  f" · 平均行动 {was['平均行动']} -> {now['平均行动']}{flag}")

    if args.报告:
        pathlib.Path(args.报告).write_text(
            json.dumps({"卡片": table, "合计": total, "抛错": failures},
                       ensure_ascii=False, indent=1) + "\n",
            encoding="utf-8",
        )
        print(f"结果写入 {args.报告}")
    return 2 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
