"""事件频次：每种事件在**一次行动内**到底会发生几次。

`限额形态` 这一轴的核心事实是「上限在哪类事件上真的会碰到」。此前（第 6/7 轮）这条是**手工分类**的：
`行动结束` 一次行动只发生一次所以上限是装饰性的，`受到伤害后` 可能多次所以上限是活的。
其实结果里就能数出来——`BattleEvent.turn` 就是 `上下文.行动序号`。

    .venv/Scripts/python.exe -X utf8 tools/事件频次.py

对每张构筑卡跑一次镜像战（与 `语料对照.py` 同一套卡与属性），把事件按 `(行动序号, 事件名)`
分组计数，于是：

    最大次数 = 1  → 该事件一次行动至多一次，写在上面的 `每次行动最多触发` 永远是装饰性的；
    最大次数 ≥ 2  → 上限在那里真的限流，是「真上限」，才值得多样化。

**退出码：0 = 正常，2 = 有战斗抛错。**
"""

from __future__ import annotations

import asyncio
import collections
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
SURFACES = (
    ("功法", "战斗/内容/功法/功法-*.json"),
    ("真意", "战斗/内容/真意/真意-*.json"),
    ("气机", "战斗/内容/气机/气机-*.json"),
    ("器律", "炼器/内容/器律-*.json"),
)


def spec(pid: str, section: str, card: str) -> CombatantSpec:
    return CombatantSpec(
        id=pid, name=pid, attributes=dict(ATTRS),
        build=(CombatBuildRef(section, card, instance_id=f"{pid}:{card}", born_order=0),),
    )


def main() -> int:
    data = ROOT / "data"
    corpus: list[tuple[str, str]] = []
    for section, pattern in SURFACES:
        for path in sorted(data.glob(pattern)):
            for entry in json.loads(path.read_text(encoding="utf-8")):
                corpus.append((section, str(entry["编号"])))

    core = build_game_services(data_dir=data).core
    stats: dict[str, dict[str, float]] = {}
    battles = 0
    failures: list[str] = []
    for section, card in corpus:
        battles += 1
        try:
            result = asyncio.run(core.combat.execute(CombatRequest(
                left_team=(spec("L", section, card),),
                right_team=(spec("R", section, card),),
                seed=20260911, action_limit=60,
            )))
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{section}:{card} {type(exc).__name__}: {exc}")
            continue
        # **必须按场分开数**：`turn` 是各场自己的行动序号，跨场累加会得到
        # 「一次行动内 1792 次」这种荒唐数（工具第一版就这么错过）。
        local: collections.Counter[tuple[int, str]] = collections.Counter(
            (event.turn, event.kind) for event in result.events
        )
        for (_turn, kind), count in local.items():
            row = stats.setdefault(kind, {"组": 0, "最大": 0, "多次组": 0, "次数": 0})
            row["组"] += 1
            row["次数"] += count
            row["最大"] = max(row["最大"], count)
            if count >= 2:
                row["多次组"] += 1
    core.database.close()

    print(f"{battles} 场镜像战 · 失败 {len(failures)} 场")
    for line in failures[:5]:
        print("  抛错 " + line)
    print(f"\n{'事件':<14}{'总次数':>8}{'行动内最大':>10}{'平均':>7}{'>=2 的行动占比':>14}")
    for kind, row in sorted(stats.items(), key=lambda kv: (-kv[1]["最大"], -kv[1]["次数"])):
        mean = row["次数"] / row["组"] if row["组"] else 0
        share = row["多次组"] / row["组"] if row["组"] else 0
        mark = "  ← 是真上限" if row["最大"] >= 2 else ""
        print(f"{kind:<14}{int(row['次数']):>8}{int(row['最大']):>10}{mean:>7.2f}{share:>13.1%}{mark}")
    live = [k for k, v in stats.items() if v["最大"] >= 2]
    print(f"\n能一次行动发生多次的事件 {len(live)} 种：{' '.join(sorted(live))}")
    print(f"至多一次的事件 {len(stats) - len(live)} 种（其上的 `每次行动最多触发` 是装饰性的）")
    return 2 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
