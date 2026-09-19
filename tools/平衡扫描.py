"""平衡扫描：在 `输出倍率` × `恢复倍率` 上扫格子，量战局长度与解决率。

`tools/战斗统计.py` 回答「现在是什么样」，这个工具回答「改哪个数会变成什么样」。

**它不在真实数据目录上动手。** 先把 `data/` 复制一份到临时目录，只在副本里改
`战斗/规则/伤害.json`，扫完临时目录整个删掉。之所以这么绕：这两个闸原本是直接
改真实文件、跑完在 `finally` 里还原，结果一次被强杀（`finally` 不会执行）把线上
数值留在了扫描途中的某一格，之后所有测量都建立在这个错误状态上。临时副本让
「进程怎么死」都不影响真实数据。

为什么要扫两个闸而不是一个：100 级满构筑实测「对敌伤害 / 血上限」与
「血气恢复 / 血上限」都是 1.1% 每行动，**恰好抵消**。单砍恢复只能把未决
从 30/39 降到 28/39，单抬输出也会被恢复按比例吃掉——两个闸是相乘关系。

    .venv/Scripts/python.exe -X utf8 tools/平衡扫描.py
    .venv/Scripts/python.exe -X utf8 tools/平衡扫描.py --等级 100 --构筑数 40
    .venv/Scripts/python.exe -X utf8 tools/平衡扫描.py --输出 100,300 --恢复 100,25
"""

from __future__ import annotations

import argparse
import asyncio
import collections
import dataclasses
import importlib.util
import io
import json
import pathlib
import shutil
import statistics
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from game.app import build_game_services  # noqa: E402
from game.core.combat.contracts import (  # noqa: E402
    CombatBuildRef,
    CombatantSpec,
    CombatRequest,
)

sys.path.insert(0, str(ROOT / "tools"))
_spec = importlib.util.spec_from_file_location("战斗统计", ROOT / "tools" / "战斗统计.py")
统计 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(统计)

RULES_RELATIVE = pathlib.Path("战斗") / "规则" / "伤害.json"


def write_rules(data_dir: pathlib.Path, 输出: int, 恢复: int) -> None:
    """改写**副本**里的伤害规则。调用方必须传临时目录。"""

    path = data_dir / RULES_RELATIVE
    body = json.loads(path.read_text(encoding="utf-8"))
    body["输出倍率"] = 输出
    body["恢复倍率"] = 恢复
    path.write_text(json.dumps(body, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def measure(data_dir: pathlib.Path, attrs: dict, builds, seeds, limit: int):
    core = build_game_services(data_dir=data_dir).core
    rows: list[dict] = []
    failures: list[str] = []
    try:
        for index, entries in enumerate(builds):
            def side(pid: str) -> CombatantSpec:
                refs = tuple(
                    CombatBuildRef(s, c, instance_id=f"{pid}:{c}", born_order=i)
                    for i, (s, c) in enumerate(entries)
                )
                return CombatantSpec(id=pid, name=pid, attributes=dict(attrs), build=refs)

            try:
                raw = dataclasses.asdict(asyncio.run(core.combat.execute(CombatRequest(
                    left_team=(side("L"),), right_team=(side("R"),),
                    seed=seeds[index % len(seeds)], action_limit=limit,
                ))))
            except Exception as exc:  # noqa: BLE001
                failures.append(
                    f"构筑{index} {type(exc).__name__}: {exc}\n      "
                    + "+".join(c for _s, c in entries)
                )
                continue

            dealt = collections.Counter()
            heal = 0.0
            casts = fails = 0
            for e in raw["events"]:
                kind = e.get("kind")
                amount = float(e.get("amount") or 0.0)
                if kind == "造成伤害后" and amount > 0 and e.get("source") != e.get("target"):
                    dealt[str(e.get("source"))] += amount
                elif kind in ("恢复后", "资源恢复后") and amount > 0:
                    if "精神" not in str((e.get("values") or {}).get("资源") or ""):
                        heal += amount
                elif kind == "技能施放后":
                    casts += 1
                elif kind == "技能施放失败后":
                    fails += 1

            sides = (raw.get("left") or {}, raw.get("right") or {})
            caps = [
                (
                    float((s.get("attributes") or {}).get("血气上限") or attrs["血气上限"]),
                    float((s.get("attributes") or {}).get("精神上限") or attrs["精神上限"]),
                )
                for s in sides
            ]
            rows.append({
                "构筑": index,
                "行动": float(raw.get("actions") or 0),
                "单方伤害": max(dealt["L"], dealt["R"]),
                "合计伤害": dealt["L"] + dealt["R"],
                "血气恢复": heal,
                "施放": casts, "失败": fails,
                # 未决读引擎自己的结论，不能看血气——有的卡会让一方
                # `active=False`（遁走、入定、放逐）而血气还满着，那种是已判出胜负。
                "未决": 统计.fight_unresolved(raw),
                "1行动": float(raw.get("actions") or 0) <= 1,
                "最低血余": min(
                    float(sides[i].get("health") or 0) / caps[i][0] for i in (0, 1)
                ),
                "最低精神余": min(
                    float(sides[i].get("spirit") or 0) / caps[i][1] for i in (0, 1)
                ),
            })
    finally:
        core.database.close()
    return rows, failures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--数据", dest="data", default=str(ROOT / "data"),
                        help="要复制的**源**数据目录；扫描在它的临时副本上跑")
    parser.add_argument("--报告", dest="report", default="_输出/平衡扫描.txt")
    parser.add_argument("--上限", dest="limit", type=int, default=60,
                        help="行动上限：到顶还没分出胜负就算未决")
    parser.add_argument("--等级", dest="等级", type=int, default=100)
    parser.add_argument("--构筑数", dest="构筑数", type=int, default=40)
    parser.add_argument("--输出", dest="输出", default="100,200,300,400")
    parser.add_argument("--恢复", dest="恢复", default="100,50,25")
    args = parser.parse_args()

    source = pathlib.Path(args.data).resolve()
    (ROOT / "_输出").mkdir(exist_ok=True)
    out = io.TextIOWrapper(open(ROOT / args.report, "wb"), encoding="utf-8")
    out.write(f"平衡扫描：{source}（在临时副本上跑，源目录不改动）\n")
    out.write(f"{args.等级} 级 · {args.构筑数} 套满构筑 · 行动上限 {args.limit}\n")
    out.write("=" * 104 + "\n")
    out.write(f"{'输出':>6} {'恢复':>6} {'样本':>5} {'抛错':>5} {'未决':>9} {'1行动':>6} "
              f"{'行动中位':>8} {'行动p90':>8} "
              f"{'单方伤害':>9} {'伤害/血池':>9} {'恢复/血池':>9} {'净/血池':>8} "
              f"{'精神余':>7}\n")

    all_failures: list[str] = []
    with tempfile.TemporaryDirectory(prefix="平衡扫描-") as work:
        sandbox = pathlib.Path(work) / "data"
        shutil.copytree(source, sandbox)
        # 属性与构筑也从副本读，免得将来有闸挪到别处时两边不一致。
        attrs = 统计.level_attributes(sandbox, args.等级)
        builds = 统计.full_builds(sandbox, args.构筑数)
        seeds = [20260911]
        pool = attrs["血气上限"]
        out.write(f"  血气上限 {pool:.0f}（单方）· 副本 {sandbox}\n")

        for 输出 in (int(v) for v in args.输出.split(",")):
            for 恢复 in (int(v) for v in args.恢复.split(",")):
                write_rules(sandbox, 输出, 恢复)
                rows, failures = measure(sandbox, attrs, builds, seeds, args.limit)
                for line in failures:
                    if line not in all_failures:
                        all_failures.append(line)
                if not rows:
                    out.write(f"{输出:>6} {恢复:>6} {'0':>5} {len(failures):>5}"
                              f"   —— 无有效样本\n")
                    continue
                actions = [r["行动"] for r in rows]
                dealt = statistics.median(r["单方伤害"] for r in rows)
                healed = statistics.median(r["血气恢复"] for r in rows)
                out.write(
                    f"{输出:>6} {恢复:>6} {len(rows):>5} {len(failures):>5} "
                    f"{sum(1 for r in rows if r['未决']):>4}/{len(rows):<4} "
                    f"{sum(1 for r in rows if r['1行动']):>6} "
                    f"{statistics.median(actions):>8.0f} "
                    f"{统计.percentile(actions, 0.90):>8.0f} "
                    f"{dealt:>9.0f} {dealt / pool * 100:>8.1f}% "
                    f"{healed / pool * 100:>8.1f}% "
                    f"{(dealt - healed) / pool * 100:>7.1f}% "
                    f"{statistics.median(r['最低精神余'] for r in rows):>7.2f}\n"
                )
                out.flush()

    out.write("\n"
              "列义：\n"
              "  `未决`    引擎判为「未分胜负」，也就是这场没打完。必须读引擎的结论，\n"
              "            不能看血气——有的卡会让一方 `active=False`（遁走、入定、放逐），\n"
              "            引擎据此判出胜负，但那一方血气还满着。\n"
              "  `1行动`   第 1 行动就结束的场次。除了真的一击必杀，主要来自上面那类\n"
              "            自我退场效果，看战局时长时要单独排掉。\n"
              "  `单方伤害` 每套里出手更多那一方的对敌伤害——这才是对着一个血池的量，\n"
              "             双方合计会把它吹成两倍。\n"
              "  `伤害/血池` 单方在整场里能打掉对面几条血。要打完一场，这个数必须大于 1，\n"
              "             而且要明显大于 `恢复/血池`，否则恢复会把输出抵消掉。\n"
              "  `净/血池`  两者之差；它才是真正的推进速度。\n"
              "  `精神余`   终局精神余量占上限比。它归零说明撞的是出手预算，不是伤害——\n"
              "             这时候再抬 `输出倍率` 只会变成精神饿死，不会变成更多伤害。\n")
    if all_failures:
        out.write(f"\n抛错的构筑 {len(all_failures)} 套（每一档都一样，与倍率无关）：\n")
        for line in all_failures:
            out.write(f"    {line}\n")
    out.flush()
    print(f"详见 {args.report}（扫描在临时副本上完成，源目录未改动）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
